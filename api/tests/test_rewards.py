"""Route rewards (SOL for taking the recommended route): config, the Mongo side (mongomock), and /plan -> claim ->
arrival -> payout with a fake Solana RPC. Nothing reaches a real cluster."""
import base64
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import httpx
import mongomock
from solders.keypair import Keypair
from solders.transaction import Transaction

from app import main, rewards, store as store_mod
from tests.test_plan import SF, FakeStore, PlanEndpoint

TREASURY = Keypair()
RIDER = str(Keypair().pubkey())
ENV = {"SOLANA_TREASURY_KEY": str(TREASURY), "SOLANA_RPC_URL": "https://api.devnet.solana.com"}


class Config(unittest.TestCase):
    def test_payouts_only_on_devnet_or_testnet_with_a_treasury(self):
        with mock.patch.dict("os.environ", ENV):
            self.assertTrue(rewards.available())
            self.assertIn(str(TREASURY.pubkey()), rewards.status())
        with mock.patch.dict("os.environ", {**ENV, "SOLANA_RPC_URL": "https://api.mainnet-beta.solana.com"}):
            self.assertFalse(rewards.available())
        with mock.patch.dict("os.environ", {**ENV, "SOLANA_TREASURY_KEY": json.dumps(list(bytes(TREASURY)))}):
            self.assertEqual(rewards.treasury().pubkey(), TREASURY.pubkey())  # solana-keygen's JSON form works too
        with mock.patch.dict("os.environ", {**ENV, "SOLANA_TREASURY_KEY": "nope"}):
            self.assertFalse(rewards.available())
        self.assertTrue(rewards.valid_wallet(RIDER))
        self.assertFalse(rewards.valid_wallet("0xabc"))


class FakeRPC:
    """A devnet RPC that hands out a blockhash and accepts transactions."""
    def __init__(self, fail=False):
        self.sent: list[Transaction] = []
        self.fail = fail

    def __call__(self, req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        if body["method"] == "getLatestBlockhash":
            return httpx.Response(200, json={"result": {"value": {"blockhash": "11111111111111111111111111111111"}}})
        if self.fail:
            return httpx.Response(200, json={"error": {"message": "insufficient funds"}})
        tx = Transaction.from_bytes(base64.b64decode(body["params"][0]))
        self.sent.append(tx)
        return httpx.Response(200, json={"result": str(tx.signatures[0])})


class MongoStore(FakeStore):
    """FakeStore's plan inputs (demo events, no traffic), with trips + rewards in the real Store over mongomock."""
    def __init__(self):
        super().__init__(traffic=[])
        self.db = mongomock.MongoClient(tz_aware=True).db
        self.real = store_mod.Store()
        self.real.db = lambda: self.db
        for name in ("save_trip", "mark_arrived", "claim_reward", "finish_reward"):
            setattr(self, name, getattr(self.real, name))

    @property
    def trips(self):
        return list(self.db.trips.find({}, {"_id": 0}))

    @trips.setter
    def trips(self, _):
        pass


class Flow(PlanEndpoint):
    def setUp(self):
        super().setUp()
        self.envp = mock.patch.dict("os.environ", ENV)
        self.envp.start()
        self.depart = (datetime.now(SF) + timedelta(days=1)).replace(hour=18, minute=30, second=0, microsecond=0)

    def tearDown(self):
        self.envp.stop()
        super().tearDown()

    def post(self, store, path, rpc=None, **kw):
        with mock.patch.object(main, "store", store), \
                mock.patch.dict(main.state, {"http": httpx.AsyncClient(transport=httpx.MockTransport(rpc or FakeRPC()))}):
            return self.client.post(path, **kw)

    def trip(self, store, left_ago=timedelta(minutes=20)) -> str:
        """A planned trip that departed `left_ago` (the claim checks the drive took a plausible time)."""
        trip_id = self.plan(store, self.depart).json()["data"]["trip_record"]["trip_id"]
        store.db.trips.update_one({"trip_id": trip_id}, {"$set": {"depart_at": datetime.now(timezone.utc) - left_ago}})
        return trip_id

    def claim(self, store, trip_id, rpc=None, wallet=RIDER, route=0):
        return self.post(store, f"/trips/{trip_id}/reward", rpc, json={"wallet": wallet, "route": route})

    def test_paid_only_after_the_trip_is_complete_on_the_recommended_route(self):
        store = MongoStore()
        body = self.plan(store, self.depart).json()
        offer = body["plan"]["reward"]
        self.assertEqual((offer["route"], offer["lamports"]), (body["plan"]["best"], rewards.REWARD_LAMPORTS))
        self.assertEqual(store.trips[0]["reward_offer"], {"route": 0, "lamports": 5_000_000, "expected_sec": 600})
        self.assertNotIn("wallet", json.dumps(store.trips, default=str))  # no wallet until the rider claims

        trip_id = self.trip(store)
        rpc = FakeRPC()
        self.assertEqual(self.claim(store, trip_id, rpc).status_code, 409)  # not arrived yet
        self.assertEqual(self.post(store, f"/trips/{trip_id}/arrived").json().get("reward"), None)
        self.assertEqual(self.claim(store, trip_id, rpc, wallet="not-a-wallet").status_code, 400)
        self.assertEqual(self.claim(store, trip_id, rpc, route=1).status_code, 409)  # drove another route
        ok = self.claim(store, trip_id, rpc)
        self.assertEqual(ok.status_code, 200, ok.text)
        got = ok.json()
        self.assertEqual((got["status"], got["sol"]), ("paid", 0.005))
        self.assertTrue(got["explorer"].endswith("?cluster=devnet"))
        [tx] = rpc.sent
        keys = [str(k) for k in tx.message.account_keys]
        self.assertEqual((keys[0], tx.message.instructions[0].data[4:12]),
                         (str(TREASURY.pubkey()), (5_000_000).to_bytes(8, "little")))
        self.assertIn(RIDER, keys)
        self.assertIn(rewards.MEMO_PROGRAM, keys)
        self.assertEqual(store.db.rewards.find_one({"trip_id": trip_id})["status"], "paid")
        self.assertEqual(self.claim(store, trip_id, rpc).status_code, 409)  # never paid twice
        self.assertEqual(len(rpc.sent), 1)

    def test_too_quick_a_trip_or_a_failed_payout_pays_nothing(self):
        store = MongoStore()
        for left_ago, rpc, want in ((timedelta(minutes=1), FakeRPC(), "too_soon"), (timedelta(hours=1), FakeRPC(fail=True), "failed")):
            trip_id = self.trip(store, left_ago)
            self.post(store, f"/trips/{trip_id}/arrived")
            self.assertEqual(self.claim(store, trip_id, rpc).json()["status"], want)
            self.assertEqual(store.db.rewards.find_one({"trip_id": trip_id})["status"], want)
            self.assertEqual(rpc.sent, [])
        with mock.patch.dict("os.environ", {"REWARD_MIN_TRIP_FRACTION": "0"}):  # stage demo: any completed trip pays
            trip_id = self.trip(store, timedelta(0))
            self.post(store, f"/trips/{trip_id}/arrived")
            self.assertEqual(self.claim(store, trip_id).json()["status"], "paid")

    def test_no_offer_without_a_treasury_or_a_logged_trip(self):
        with mock.patch.dict("os.environ", {"SOLANA_TREASURY_KEY": ""}):
            store = MongoStore()
            body = self.plan(store, self.depart).json()
            self.assertIsNone(body["plan"]["reward"])
            self.assertNotIn("reward_offer", store.trips[0])
        with mock.patch.dict("os.environ", {**ENV, "SOLANA_TREASURY_KEY": ""}):
            r = self.claim(store, body["data"]["trip_record"]["trip_id"])
            self.assertEqual(r.status_code, 503)
        self.assertIsNone(self.plan(MongoStore(), self.depart, save="false").json()["plan"]["reward"])
        self.assertEqual(store.db.rewards.count_documents({}), 0)


if __name__ == "__main__":
    unittest.main()
