# Simulation checks: Castro Street Fair 2026

Generated 2026-09-26T11:45:30+00:00 by `python -m eventsim check --event castro`. Each row compares an event run with its no-event control (same seed and background demand). All numbers are simulated.

- Event/control pairs: 200; families: 100
- SUMO runtime per run: median 67 s (event), 52 s (control)
- Vehicles entering fully closed edges in steady state: 10; during the first 20 min after a closure opens (vehicles already committed past the last trigger edge, or already on it): 252
- Unfinished at sim end (event runs): total 0, max 0; not inserted / no route: 0
- Teleports: event runs median 26 (max 93), controls median 16; teleported vehicles still count as arrived, so they are listed per run
- Background time loss: event 121 s vs control 114 s per trip (mean over runs)
- Runs whose event adds ≥ 1 vehicle-hour of delay in its peak 10 min: 200/200
- Runs recovering (extra delay < 10% of peak) before sim end: 200/200
- Status: closure leaks in 8 runs

| run | variant | event veh | bg vph | trips | unfinished | tele (ev/ctl) | closed entries | bg loss ev/ctl s | depart delay ev/ctl s | peak extra veh·h @ | recovered | detour edges (top streets) |
|---|---|---:|---:|---:|---:|---|---:|---|---|---|---|---|
| f000_s0_ev | permit | 2394 | 1311 | 18208 | 0 | 49/27 | 0 | 135/121 | 1/1 | 23.8 @ 17:50 | 19:00 | 184 (Dolores Street (25), Church Street (25), 19th Street (16), Noe Street (15)) |
| f000_s1_ev | permit | 2394 | 1311 | 18409 | 0 | 46/23 | 0 | 138/121 | 1/1 | 26.7 @ 17:40 | 19:00 | 200 (Church Street (26), Dolores Street (26), Sanchez Street (16), 19th Street (16)) |
| f001_s0_ev | permit_market_open | 1558 | 353 | 6742 | 0 | 8/0 | 0 | 112/105 | 1/0 | 8.5 @ 12:40 | 18:50 | 22 (Market Street (9), Noe Street (7), 17th Street (3), Roosevelt Way (2)) |
| f001_s1_ev | permit_market_open | 1558 | 353 | 6704 | 0 | 10/3 | 0 | 113/106 | 1/1 | 9.3 @ 12:50 | 18:40 | 18 (Market Street (9), Noe Street (5), Roosevelt Way (2), 17th Street (1)) |
| f002_s0_ev | permit | 1275 | 971 | 12675 | 0 | 8/16 | 0 | 113/109 | 1/1 | 3.3 @ 17:30 | 19:20 | 65 (Sanchez Street (13), 19th Street (13), Noe Street (12), 20th Street (6)) |
| f002_s1_ev | permit | 1275 | 971 | 12713 | 0 | 21/12 | 0 | 113/108 | 1/1 | 3.9 @ 17:20 | 19:50 | 61 (19th Street (13), Noe Street (12), Sanchez Street (9), 20th Street (7)) |
| f003_s0_ev | permit_market_one_lane | 655 | 1333 | 15038 | 0 | 35/35 | 0 | 114/111 | 1/1 | 2.9 @ 13:10 | 19:50 | 54 (Noe Street (12), 19th Street (12), Sanchez Street (10), 20th Street (6)) |
| f003_s1_ev | permit_market_one_lane | 655 | 1333 | 15165 | 0 | 46/29 | 0 | 114/110 | 1/1 | 3.1 @ 13:00 | 20:10 | 55 (Noe Street (12), 19th Street (12), Sanchez Street (11), 20th Street (6)) |
| f004_s0_ev | permit_market_one_lane | 381 | 382 | 4743 | 0 | 0/2 | 0 | 105/104 | 0/0 | 1.5 @ 17:30 | 19:20 | 11 (19th Street (6), Noe Street (5)) |
| f004_s1_ev | permit_market_one_lane | 381 | 382 | 4685 | 0 | 2/1 | 0 | 105/104 | 0/0 | 1.5 @ 17:20 | 19:00 | 9 (19th Street (7), Noe Street (2)) |
| f005_s0_ev | permit_market_open | 2441 | 295 | 7804 | 0 | 4/0 | 0 | 124/116 | 0/0 | 11.7 @ 12:50 | 19:20 | 73 (Market Street (15), Noe Street (12), Church Street (8), 17th Street (7)) |
| f005_s1_ev | permit_market_open | 2441 | 295 | 7969 | 0 | 6/0 | 0 | 126/116 | 1/0 | 11.4 @ 12:50 | 19:20 | 82 (Market Street (15), Noe Street (15), Church Street (9), 17th Street (7)) |
| f006_s0_ev | permit | 485 | 1366 | 14985 | 0 | 31/34 | 0 | 120/119 | 1/1 | 2.8 @ 18:00 | 19:40 | 56 (19th Street (12), Noe Street (11), Sanchez Street (10), 20th Street (6)) |
| f006_s1_ev | permit | 485 | 1366 | 15088 | 0 | 39/50 | 0 | 121/120 | 1/1 | 2.4 @ 18:00 | 19:20 | 61 (Sanchez Street (13), 19th Street (13), Noe Street (11), 20th Street (8)) |
| f007_s0_ev | permit_market_open | 1557 | 829 | 11865 | 0 | 25/12 | 0 | 136/127 | 1/1 | 7.1 @ 18:30 | 20:10 | 14 (Noe Street (5), Market Street (4), Roosevelt Way (2), Temple Street (1)) |
| f007_s1_ev | permit_market_open | 1557 | 829 | 11460 | 0 | 27/10 | 0 | 135/126 | 1/0 | 7.9 @ 18:30 | 20:10 | 16 (Noe Street (6), Market Street (4), Roosevelt Way (2), 19th Street (2)) |
| f008_s0_ev | permit | 748 | 312 | 4574 | 0 | 5/0 | 0 | 117/114 | 0/0 | 2.7 @ 18:20 | 19:40 | 14 (19th Street (7), Noe Street (5), Sanchez Street (1), Roosevelt Way (1)) |
| f008_s1_ev | permit | 748 | 312 | 4694 | 0 | 9/2 | 0 | 118/116 | 1/0 | 3.1 @ 18:00 | 19:40 | 15 (19th Street (8), Noe Street (6), Sanchez Street (1)) |
| f009_s0_ev | permit_market_one_lane | 648 | 838 | 9788 | 0 | 9/9 | 0 | 122/117 | 1/0 | 2.8 @ 17:10 | 18:50 | 46 (Noe Street (12), 19th Street (12), Sanchez Street (6), Roosevelt Way (4)) |
| f009_s1_ev | permit_market_one_lane | 648 | 838 | 10073 | 0 | 12/14 | 0 | 121/117 | 1/1 | 3.9 @ 17:30 | 18:40 | 47 (Noe Street (12), 19th Street (12), Sanchez Street (7), Roosevelt Way (4)) |
| f010_s0_ev | permit | 1532 | 966 | 12997 | 0 | 17/14 | 0 | 109/104 | 1/1 | 7.8 @ 17:40 | 19:00 | 81 (19th Street (13), Noe Street (12), Church Street (10), Sanchez Street (10)) |
| f010_s1_ev | permit | 1532 | 966 | 13017 | 0 | 27/20 | 0 | 109/104 | 1/1 | 8.4 @ 17:40 | 18:50 | 86 (19th Street (13), Noe Street (12), Church Street (11), Sanchez Street (11)) |
| f011_s0_ev | permit | 2747 | 1283 | 18624 | 0 | 54/21 | 1 | 123/114 | 1/1 | 18.3 @ 18:30 | 19:50 | 107 (Church Street (15), Sanchez Street (14), 19th Street (14), Noe Street (12)) |
| f011_s1_ev | permit | 2747 | 1283 | 18704 | 0 | 29/21 | 0 | 122/114 | 1/1 | 14.2 @ 18:30 | 19:40 | 108 (19th Street (15), Church Street (14), Sanchez Street (13), Noe Street (12)) |
| f012_s0_ev | permit_market_open | 639 | 1151 | 13089 | 0 | 38/47 | 0 | 132/127 | 1/1 | 3.1 @ 18:20 | 20:30 | 6 (Market Street (2), Roosevelt Way (2), Noe Street (2)) |
| f012_s1_ev | permit_market_open | 639 | 1151 | 13100 | 0 | 32/11 | 0 | 132/125 | 1/1 | 4.1 @ 18:20 | 20:10 | 7 (Market Street (3), Roosevelt Way (2), Noe Street (2)) |
| f013_s0_ev | permit_market_one_lane | 1329 | 971 | 12607 | 0 | 24/13 | 0 | 110/104 | 1/0 | 5.1 @ 17:00 | 19:00 | 73 (Sanchez Street (14), 19th Street (13), Noe Street (12), 20th Street (8)) |
| f013_s1_ev | permit_market_one_lane | 1329 | 971 | 12635 | 0 | 10/8 | 0 | 110/104 | 1/0 | 7.2 @ 17:10 | 18:50 | 83 (Sanchez Street (14), 19th Street (13), Noe Street (12), 20th Street (8)) |
| f014_s0_ev | permit | 281 | 1204 | 13063 | 0 | 14/17 | 0 | 113/110 | 1/1 | 1.2 @ 18:40 | 20:30 | 45 (19th Street (11), Noe Street (10), Sanchez Street (7), 20th Street (5)) |
| f014_s1_ev | permit | 281 | 1204 | 12982 | 0 | 17/12 | 0 | 112/109 | 1/0 | 1.3 @ 12:00 | 20:00 | 40 (19th Street (11), Sanchez Street (7), Noe Street (7), Roosevelt Way (4)) |
| f015_s0_ev | permit | 1693 | 977 | 13276 | 0 | 41/14 | 0 | 131/121 | 1/1 | 18.2 @ 17:20 | 18:10 | 128 (Church Street (17), Dolores Street (14), Sanchez Street (14), 19th Street (14)) |
| f015_s1_ev | permit | 1693 | 977 | 13451 | 0 | 39/13 | 0 | 130/121 | 1/1 | 21.1 @ 17:10 | 18:00 | 132 (Church Street (16), Dolores Street (15), 19th Street (14), Sanchez Street (14)) |
| f016_s0_ev | permit_market_open | 2354 | 1195 | 17006 | 0 | 93/35 | 0 | 146/132 | 1/1 | 29.4 @ 17:30 | 18:30 | 179 (Dolores Street (22), Church Street (21), Noe Street (19), Market Street (16)) |
| f016_s1_ev | permit_market_open | 2354 | 1195 | 17094 | 0 | 80/20 | 0 | 144/129 | 1/1 | 22.2 @ 17:30 | 18:30 | 174 (Church Street (24), Noe Street (19), Dolores Street (18), Sanchez Street (14)) |
| f017_s0_ev | permit | 2037 | 991 | 14095 | 0 | 32/10 | 0 | 138/128 | 1/1 | 17.5 @ 18:10 | 19:10 | 96 (Sanchez Street (14), 19th Street (13), Noe Street (12), Church Street (11)) |
| f017_s1_ev | permit | 2037 | 991 | 14270 | 0 | 47/16 | 0 | 138/129 | 1/1 | 21.1 @ 18:00 | 19:10 | 97 (Sanchez Street (14), 19th Street (13), Noe Street (12), Church Street (12)) |
| f018_s0_ev | permit_market_open | 406 | 1086 | 12036 | 0 | 25/26 | 0 | 132/127 | 1/1 | 2.4 @ 17:00 | 19:00 | 6 (Market Street (2), Roosevelt Way (2), Noe Street (2)) |
| f018_s1_ev | permit_market_open | 406 | 1086 | 11857 | 0 | 5/12 | 0 | 132/127 | 0/1 | 3.2 @ 13:50 | 19:00 | 5 (Market Street (2), Roosevelt Way (2), Noe Street (1)) |
| f019_s0_ev | permit_market_open | 1327 | 1053 | 13428 | 0 | 59/17 | 0 | 132/122 | 1/1 | 7.1 @ 18:10 | 20:30 | 29 (19th Street (7), Noe Street (6), Market Street (4), 17th Street (4)) |
| f019_s1_ev | permit_market_open | 1327 | 1053 | 13378 | 0 | 31/31 | 0 | 132/123 | 1/1 | 7.4 @ 13:10 | 20:20 | 26 (Noe Street (6), 19th Street (5), Market Street (4), Roosevelt Way (4)) |
| f020_s0_ev | permit | 2997 | 960 | 15956 | 0 | 48/27 | 0 | 122/108 | 1/1 | 31.7 @ 17:50 | 18:40 | 249 (Church Street (31), Dolores Street (30), Noe Street (19), Sanchez Street (19)) |
| f020_s1_ev | permit | 2997 | 960 | 15748 | 0 | 44/23 | 0 | 124/108 | 1/1 | 30.5 @ 17:40 | 18:40 | 248 (Church Street (31), Dolores Street (30), Noe Street (20), Sanchez Street (19)) |
| f021_s0_ev | permit | 1773 | 1195 | 15605 | 0 | 19/24 | 0 | 119/114 | 1/1 | 7.2 @ 18:30 | 19:50 | 63 (Sanchez Street (14), 19th Street (13), Noe Street (12), 20th Street (6)) |
| f021_s1_ev | permit | 1773 | 1195 | 15833 | 0 | 33/26 | 0 | 118/113 | 1/1 | 6.9 @ 18:40 | 19:50 | 71 (19th Street (13), Noe Street (12), Sanchez Street (11), 20th Street (8)) |
| f022_s0_ev | permit_market_open | 482 | 1197 | 13344 | 0 | 17/20 | 0 | 125/121 | 1/1 | 2.2 @ 11:50 | 20:10 | 6 (Market Street (2), Roosevelt Way (2), Noe Street (2)) |
| f022_s1_ev | permit_market_open | 482 | 1197 | 13316 | 0 | 32/29 | 0 | 125/120 | 1/1 | 2.6 @ 18:20 | 20:00 | 4 (Market Street (2), Noe Street (2)) |
| f023_s0_ev | permit | 1064 | 829 | 10576 | 0 | 13/8 | 0 | 115/110 | 1/0 | 7.2 @ 17:40 | 18:50 | 55 (19th Street (12), Noe Street (11), Sanchez Street (9), Roosevelt Way (5)) |
| f023_s1_ev | permit | 1064 | 829 | 10478 | 0 | 13/7 | 0 | 112/108 | 0/0 | 8.8 @ 17:50 | 18:40 | 54 (Noe Street (12), 19th Street (12), Sanchez Street (9), 20th Street (5)) |
| f024_s0_ev | permit_market_one_lane | 877 | 780 | 9720 | 0 | 13/14 | 1 | 114/112 | 1/1 | 2.5 @ 18:20 | 20:20 | 39 (Noe Street (11), 19th Street (10), Roosevelt Way (4), Sanchez Street (3)) |
| f024_s1_ev | permit_market_one_lane | 877 | 780 | 9588 | 0 | 11/8 | 0 | 116/112 | 1/1 | 2.5 @ 18:30 | 20:30 | 39 (Noe Street (11), 19th Street (10), Sanchez Street (4), Roosevelt Way (4)) |
| f025_s0_ev | permit | 509 | 913 | 10521 | 0 | 24/13 | 0 | 108/105 | 1/1 | 2.2 @ 12:10 | 20:10 | 42 (19th Street (12), Sanchez Street (9), Noe Street (9), Roosevelt Way (4)) |
| f025_s1_ev | permit | 509 | 913 | 10481 | 0 | 9/13 | 0 | 107/104 | 0/1 | 2.3 @ 12:00 | 20:10 | 45 (19th Street (12), Noe Street (11), Sanchez Street (7), Roosevelt Way (4)) |
| f026_s0_ev | permit | 617 | 1085 | 12437 | 0 | 22/18 | 0 | 127/126 | 1/1 | 2.6 @ 18:20 | 19:40 | 48 (19th Street (12), Noe Street (11), Sanchez Street (9), Roosevelt Way (4)) |
| f026_s1_ev | permit | 617 | 1085 | 12339 | 0 | 20/23 | 0 | 128/127 | 1/1 | 3.4 @ 13:30 | 19:40 | 50 (19th Street (12), Noe Street (11), Sanchez Street (9), 20th Street (5)) |
| f027_s0_ev | permit | 852 | 1028 | 12216 | 0 | 13/11 | 0 | 118/117 | 1/1 | 6.6 @ 17:30 | 18:20 | 55 (19th Street (12), Noe Street (11), Sanchez Street (10), 20th Street (6)) |
| f027_s1_ev | permit | 852 | 1028 | 12335 | 0 | 30/19 | 0 | 119/118 | 1/1 | 6.2 @ 17:30 | 18:20 | 59 (19th Street (13), Noe Street (11), Sanchez Street (10), 20th Street (6)) |
| f028_s0_ev | permit_market_one_lane | 614 | 1307 | 14690 | 0 | 24/9 | 0 | 121/120 | 1/1 | 4.8 @ 18:10 | 19:10 | 54 (Noe Street (12), 19th Street (12), Sanchez Street (9), 20th Street (7)) |
| f028_s1_ev | permit_market_one_lane | 614 | 1307 | 14734 | 0 | 24/24 | 0 | 120/119 | 1/1 | 4.9 @ 18:20 | 19:10 | 54 (Noe Street (12), 19th Street (12), Sanchez Street (9), 20th Street (7)) |
| f029_s0_ev | permit | 1842 | 1262 | 16829 | 0 | 30/17 | 0 | 125/121 | 1/1 | 14.9 @ 17:50 | 18:50 | 103 (19th Street (15), Sanchez Street (14), Noe Street (12), Church Street (9)) |
| f029_s1_ev | permit | 1842 | 1262 | 16532 | 0 | 28/21 | 0 | 125/122 | 1/1 | 14.2 @ 17:50 | 18:50 | 103 (19th Street (15), Sanchez Street (14), Noe Street (12), Church Street (10)) |
| f030_s0_ev | permit_market_one_lane | 973 | 1337 | 15686 | 0 | 14/26 | 0 | 124/123 | 1/1 | 5.0 @ 12:00 | 19:30 | 63 (19th Street (13), Sanchez Street (12), Noe Street (12), 20th Street (7)) |
| f030_s1_ev | permit_market_one_lane | 973 | 1337 | 15759 | 0 | 28/13 | 0 | 123/121 | 1/1 | 4.7 @ 11:30 | 19:20 | 62 (19th Street (13), Noe Street (12), Sanchez Street (11), 20th Street (7)) |
| f031_s0_ev | permit | 2652 | 1163 | 17206 | 0 | 45/9 | 0 | 116/106 | 1/1 | 27.2 @ 17:30 | 18:20 | 178 (Church Street (24), Dolores Street (21), Noe Street (18), 19th Street (15)) |
| f031_s1_ev | permit | 2652 | 1163 | 17411 | 0 | 45/22 | 1 | 115/107 | 1/1 | 28.6 @ 17:30 | 18:10 | 186 (Church Street (26), Dolores Street (26), Noe Street (18), 19th Street (16)) |
| f032_s0_ev | permit | 1138 | 798 | 10511 | 0 | 12/9 | 0 | 121/116 | 1/0 | 5.2 @ 17:10 | 18:50 | 62 (Noe Street (12), 19th Street (12), Sanchez Street (8), Roosevelt Way (5)) |
| f032_s1_ev | permit | 1138 | 798 | 10402 | 0 | 15/6 | 0 | 121/115 | 1/0 | 5.3 @ 17:20 | 19:00 | 60 (Noe Street (12), 19th Street (12), Sanchez Street (9), Roosevelt Way (5)) |
| f033_s0_ev | permit_market_open | 1538 | 386 | 7142 | 0 | 11/1 | 0 | 125/117 | 1/0 | 5.1 @ 17:40 | 19:30 | 10 (Market Street (8), Noe Street (2)) |
| f033_s1_ev | permit_market_open | 1538 | 386 | 7102 | 0 | 4/2 | 0 | 122/115 | 0/0 | 4.8 @ 17:50 | 19:40 | 11 (Market Street (7), Roosevelt Way (2), Noe Street (2)) |
| f034_s0_ev | permit | 195 | 1170 | 12563 | 0 | 16/21 | 0 | 106/104 | 1/1 | 1.7 @ 17:20 | 18:40 | 47 (19th Street (12), Noe Street (10), Sanchez Street (9), Roosevelt Way (4)) |
| f034_s1_ev | permit | 195 | 1170 | 12438 | 0 | 23/29 | 0 | 108/105 | 1/1 | 1.1 @ 12:30 | 18:40 | 46 (19th Street (12), Noe Street (10), Sanchez Street (8), Roosevelt Way (4)) |
| f035_s0_ev | permit | 1945 | 1195 | 16074 | 0 | 44/33 | 0 | 114/104 | 1/1 | 22.6 @ 17:30 | 18:20 | 195 (Church Street (28), Dolores Street (28), Sanchez Street (16), 19th Street (16)) |
| f035_s1_ev | permit | 1945 | 1195 | 16364 | 0 | 33/19 | 0 | 114/102 | 1/1 | 20.1 @ 17:20 | 18:20 | 188 (Dolores Street (28), Church Street (26), 19th Street (16), Sanchez Street (16)) |
| f036_s0_ev | permit | 846 | 722 | 9150 | 0 | 14/11 | 0 | 109/106 | 0/1 | 8.6 @ 18:20 | 19:00 | 36 (Noe Street (10), 19th Street (9), Sanchez Street (7), Roosevelt Way (4)) |
| f036_s1_ev | permit | 846 | 722 | 9030 | 0 | 13/6 | 0 | 110/107 | 1/0 | 8.4 @ 18:10 | 19:00 | 34 (19th Street (9), Sanchez Street (7), Noe Street (7), Roosevelt Way (4)) |
| f037_s0_ev | permit_market_open | 1199 | 1173 | 14564 | 0 | 40/17 | 0 | 127/117 | 1/1 | 7.7 @ 12:10 | 19:00 | 37 (Noe Street (9), Market Street (5), 17th Street (5), Roosevelt Way (4)) |
| f037_s1_ev | permit_market_open | 1199 | 1173 | 14354 | 0 | 49/14 | 0 | 127/116 | 1/1 | 8.0 @ 12:40 | 19:10 | 33 (Noe Street (10), 19th Street (5), Market Street (4), Roosevelt Way (4)) |
| f038_s0_ev | permit_market_one_lane | 2939 | 331 | 9362 | 0 | 50/0 | 0 | 125/115 | 1/0 | 26.9 @ 17:50 | 18:40 | 193 (Church Street (25), Dolores Street (23), Noe Street (18), Sanchez Street (16)) |
| f038_s1_ev | permit_market_one_lane | 2939 | 331 | 9327 | 0 | 35/1 | 0 | 125/115 | 1/0 | 26.2 @ 17:50 | 18:50 | 193 (Church Street (23), Dolores Street (22), Noe Street (19), Sanchez Street (16)) |
| f039_s0_ev | permit_market_one_lane | 1475 | 787 | 10979 | 0 | 8/7 | 0 | 108/104 | 1/0 | 4.2 @ 17:40 | 19:40 | 55 (Noe Street (12), 19th Street (12), Sanchez Street (9), Roosevelt Way (5)) |
| f039_s1_ev | permit_market_one_lane | 1475 | 787 | 10907 | 0 | 12/9 | 0 | 108/104 | 0/1 | 5.5 @ 18:00 | 19:50 | 59 (19th Street (13), Noe Street (12), Sanchez Street (9), Roosevelt Way (5)) |
| f040_s0_ev | permit | 1758 | 907 | 12791 | 0 | 11/12 | 0 | 119/113 | 1/1 | 8.6 @ 18:40 | 20:00 | 46 (19th Street (11), Noe Street (11), Sanchez Street (7), Roosevelt Way (4)) |
| f040_s1_ev | permit | 1758 | 907 | 12890 | 0 | 20/15 | 0 | 121/114 | 1/1 | 8.6 @ 18:40 | 20:00 | 48 (19th Street (12), Noe Street (11), Sanchez Street (7), Roosevelt Way (4)) |
| f041_s0_ev | permit | 997 | 1169 | 13895 | 0 | 20/21 | 0 | 118/112 | 1/1 | 8.1 @ 18:10 | 19:30 | 52 (19th Street (12), Noe Street (11), Sanchez Street (9), 20th Street (5)) |
| f041_s1_ev | permit | 997 | 1169 | 14156 | 0 | 26/23 | 0 | 117/112 | 1/1 | 7.5 @ 18:20 | 19:30 | 54 (19th Street (12), Noe Street (11), Sanchez Street (9), 20th Street (6)) |
| f042_s0_ev | permit | 1011 | 1108 | 13250 | 0 | 6/18 | 0 | 121/120 | 0/1 | 5.5 @ 18:00 | 19:30 | 54 (19th Street (12), Noe Street (11), Sanchez Street (9), Roosevelt Way (5)) |
| f042_s1_ev | permit | 1011 | 1108 | 13287 | 0 | 27/21 | 0 | 121/118 | 1/1 | 6.6 @ 18:10 | 19:10 | 55 (19th Street (12), Sanchez Street (11), Noe Street (11), Roosevelt Way (5)) |
| f043_s0_ev | permit | 1112 | 813 | 10576 | 0 | 11/10 | 0 | 116/112 | 1/1 | 5.7 @ 17:40 | 19:00 | 45 (19th Street (12), Noe Street (10), Sanchez Street (8), Roosevelt Way (4)) |
| f043_s1_ev | permit | 1112 | 813 | 10543 | 0 | 18/11 | 0 | 116/112 | 1/1 | 5.6 @ 17:50 | 19:20 | 48 (19th Street (12), Noe Street (11), Sanchez Street (8), Roosevelt Way (4)) |
| f044_s0_ev | permit_market_open | 993 | 997 | 12278 | 0 | 25/15 | 0 | 125/116 | 1/0 | 6.4 @ 13:20 | 19:30 | 13 (Noe Street (7), Market Street (2), Roosevelt Way (2), 16th Street (1)) |
| f044_s1_ev | permit_market_open | 993 | 997 | 12218 | 0 | 38/22 | 0 | 126/117 | 1/1 | 7.1 @ 13:20 | 19:40 | 9 (Noe Street (4), Market Street (2), Roosevelt Way (2), Temple Street (1)) |
| f045_s0_ev | permit | 389 | 958 | 10626 | 0 | 12/12 | 0 | 121/117 | 0/0 | 2.2 @ 18:40 | 20:00 | 37 (19th Street (9), Sanchez Street (7), Noe Street (7), Roosevelt Way (4)) |
| f045_s1_ev | permit | 389 | 958 | 10622 | 0 | 10/18 | 0 | 119/116 | 1/1 | 2.2 @ 18:40 | 20:00 | 37 (19th Street (10), Noe Street (8), Sanchez Street (7), Roosevelt Way (4)) |
| f046_s0_ev | permit | 698 | 1085 | 12508 | 0 | 27/15 | 0 | 124/117 | 1/1 | 4.6 @ 12:40 | 19:50 | 55 (19th Street (12), Noe Street (11), Sanchez Street (9), 20th Street (6)) |
| f046_s1_ev | permit | 698 | 1085 | 12457 | 0 | 22/21 | 0 | 126/118 | 1/1 | 5.5 @ 12:30 | 19:50 | 56 (19th Street (12), Noe Street (11), Sanchez Street (9), Church Street (6)) |
| f047_s0_ev | permit | 417 | 1273 | 13730 | 0 | 27/37 | 0 | 123/123 | 1/1 | 2.6 @ 18:20 | 19:00 | 52 (19th Street (12), Noe Street (11), Sanchez Street (10), Roosevelt Way (5)) |
| f047_s1_ev | permit | 417 | 1273 | 14184 | 0 | 41/26 | 0 | 123/122 | 1/1 | 2.9 @ 18:20 | 19:00 | 51 (19th Street (12), Noe Street (11), Sanchez Street (9), 20th Street (6)) |
| f048_s0_ev | permit | 1571 | 1374 | 17085 | 0 | 32/18 | 0 | 129/120 | 1/1 | 5.7 @ 18:20 | 19:30 | 97 (19th Street (15), Sanchez Street (14), Church Street (12), Noe Street (12)) |
| f048_s1_ev | permit | 1571 | 1374 | 17337 | 0 | 51/57 | 0 | 129/120 | 1/1 | 6.4 @ 17:40 | 19:30 | 97 (Church Street (14), Sanchez Street (14), 19th Street (13), Noe Street (12)) |
| f049_s0_ev | permit_market_one_lane | 2028 | 813 | 12405 | 0 | 26/8 | 0 | 131/126 | 1/0 | 10.9 @ 17:00 | 18:30 | 109 (Church Street (16), Sanchez Street (14), 19th Street (13), Noe Street (12)) |
| f049_s1_ev | permit_market_one_lane | 2028 | 813 | 12253 | 0 | 25/3 | 2 | 131/126 | 1/0 | 9.8 @ 17:10 | 18:40 | 106 (Sanchez Street (14), Church Street (14), 19th Street (13), Noe Street (12)) |
| f050_s0_ev | permit_market_one_lane | 301 | 1235 | 13430 | 0 | 26/13 | 0 | 116/115 | 1/1 | 1.4 @ 19:00 | 19:40 | 48 (19th Street (12), Noe Street (10), Sanchez Street (9), 20th Street (5)) |
| f050_s1_ev | permit_market_one_lane | 301 | 1235 | 13316 | 0 | 20/10 | 0 | 116/116 | 1/0 | 1.4 @ 18:50 | 19:50 | 51 (Noe Street (12), 19th Street (12), Sanchez Street (9), Roosevelt Way (5)) |
| f051_s0_ev | permit_market_one_lane | 1183 | 830 | 10905 | 0 | 10/11 | 0 | 120/115 | 1/1 | 4.5 @ 18:30 | 20:10 | 55 (Noe Street (12), 19th Street (12), Sanchez Street (10), 20th Street (5)) |
| f051_s1_ev | permit_market_one_lane | 1183 | 830 | 10783 | 0 | 19/6 | 0 | 119/114 | 1/0 | 4.7 @ 18:00 | 19:50 | 53 (Noe Street (12), 19th Street (12), Sanchez Street (8), Roosevelt Way (5)) |
| f052_s0_ev | permit | 763 | 394 | 5676 | 0 | 2/2 | 0 | 112/110 | 0/0 | 3.0 @ 14:10 | 18:30 | 24 (19th Street (9), Noe Street (7), Roosevelt Way (4), Sanchez Street (3)) |
| f052_s1_ev | permit | 763 | 394 | 5560 | 0 | 3/3 | 0 | 116/112 | 0/0 | 2.9 @ 14:00 | 18:50 | 27 (19th Street (9), Noe Street (7), Roosevelt Way (4), Sanchez Street (3)) |
| f053_s0_ev | permit | 1059 | 1008 | 12470 | 0 | 31/25 | 0 | 125/117 | 1/1 | 5.9 @ 17:30 | 19:20 | 67 (19th Street (13), Sanchez Street (12), Noe Street (11), Roosevelt Way (6)) |
| f053_s1_ev | permit | 1059 | 1008 | 12452 | 0 | 29/21 | 0 | 124/118 | 1/1 | 5.5 @ 17:30 | 19:30 | 59 (Noe Street (12), 19th Street (12), Sanchez Street (10), 20th Street (6)) |
| f054_s0_ev | permit | 1673 | 743 | 10844 | 0 | 23/10 | 0 | 113/107 | 1/1 | 7.2 @ 17:50 | 19:00 | 86 (Noe Street (12), 19th Street (12), Sanchez Street (11), Church Street (10)) |
| f054_s1_ev | permit | 1673 | 743 | 10973 | 0 | 8/1 | 0 | 113/106 | 1/0 | 7.2 @ 17:30 | 19:00 | 93 (19th Street (13), Noe Street (12), Church Street (12), Sanchez Street (10)) |
| f055_s0_ev | permit | 454 | 1188 | 13030 | 0 | 18/21 | 0 | 116/111 | 1/0 | 2.0 @ 18:00 | 19:40 | 47 (19th Street (11), Noe Street (11), Sanchez Street (8), 20th Street (5)) |
| f055_s1_ev | permit | 454 | 1188 | 13234 | 0 | 21/22 | 0 | 116/111 | 1/1 | 2.1 @ 18:10 | 19:30 | 51 (19th Street (12), Noe Street (11), Sanchez Street (9), Roosevelt Way (5)) |
| f056_s0_ev | permit_market_open | 1257 | 789 | 10690 | 0 | 12/7 | 0 | 121/114 | 1/1 | 8.5 @ 17:50 | 18:50 | 7 (Market Street (3), Roosevelt Way (2), Noe Street (2)) |
| f056_s1_ev | permit_market_open | 1257 | 789 | 10701 | 0 | 16/9 | 0 | 121/114 | 1/1 | 9.5 @ 18:00 | 18:50 | 8 (Market Street (3), Roosevelt Way (2), Noe Street (2), 16th Street (1)) |
| f057_s0_ev | permit_market_one_lane | 2979 | 1389 | 20325 | 0 | 67/51 | 0 | 133/123 | 1/1 | 17.5 @ 13:40 | 19:10 | 244 (Church Street (30), Dolores Street (30), Noe Street (19), Sanchez Street (17)) |
| f057_s1_ev | permit_market_one_lane | 2979 | 1389 | 20065 | 0 | 66/33 | 0 | 136/123 | 1/1 | 19.9 @ 13:50 | 19:10 | 246 (Dolores Street (30), Church Street (28), Noe Street (21), Sanchez Street (17)) |
| f058_s0_ev | permit | 543 | 1260 | 14239 | 0 | 36/14 | 0 | 115/110 | 1/1 | 4.0 @ 18:10 | 19:10 | 53 (19th Street (12), Noe Street (11), Sanchez Street (9), 20th Street (6)) |
| f058_s1_ev | permit | 543 | 1260 | 14112 | 0 | 42/35 | 0 | 115/110 | 1/1 | 4.3 @ 18:00 | 19:20 | 53 (19th Street (12), Noe Street (11), Sanchez Street (9), 20th Street (6)) |
| f059_s0_ev | permit_market_one_lane | 2140 | 852 | 13029 | 0 | 11/9 | 0 | 120/117 | 1/1 | 14.7 @ 18:50 | 19:30 | 60 (Sanchez Street (13), 19th Street (13), Noe Street (12), 20th Street (5)) |
| f059_s1_ev | permit_market_one_lane | 2140 | 852 | 12901 | 0 | 28/21 | 0 | 123/120 | 1/1 | 15.7 @ 18:40 | 19:30 | 61 (Noe Street (12), 19th Street (12), Sanchez Street (10), 20th Street (6)) |
| f060_s0_ev | permit_market_open | 2907 | 999 | 16086 | 0 | 66/24 | 2 | 125/112 | 1/1 | 16.8 @ 11:50 | 18:50 | 142 (Church Street (18), Market Street (18), Dolores Street (18), Noe Street (13)) |
| f060_s1_ev | permit_market_open | 2907 | 999 | 16017 | 0 | 42/19 | 0 | 122/110 | 1/1 | 16.5 @ 11:50 | 18:50 | 159 (Market Street (22), Church Street (19), Dolores Street (19), Noe Street (18)) |
| f061_s0_ev | permit_market_open | 2230 | 1042 | 15311 | 0 | 36/22 | 0 | 118/107 | 1/1 | 9.1 @ 18:50 | 20:20 | 28 (Noe Street (9), Roosevelt Way (4), 19th Street (4), Market Street (3)) |
| f061_s1_ev | permit_market_open | 2230 | 1042 | 15186 | 0 | 38/18 | 0 | 119/109 | 1/1 | 8.7 @ 18:40 | 20:20 | 24 (Noe Street (9), Roosevelt Way (4), 19th Street (4), Market Street (3)) |
| f062_s0_ev | permit | 402 | 1173 | 12843 | 0 | 28/45 | 0 | 112/109 | 1/1 | 2.7 @ 17:10 | 18:30 | 53 (19th Street (12), Noe Street (11), Sanchez Street (9), 20th Street (6)) |
| f062_s1_ev | permit | 402 | 1173 | 13000 | 0 | 9/22 | 0 | 112/108 | 1/1 | 2.5 @ 17:30 | 18:20 | 51 (19th Street (12), Noe Street (11), Sanchez Street (9), 20th Street (6)) |
| f063_s0_ev | permit_market_one_lane | 307 | 1137 | 12414 | 0 | 30/26 | 0 | 111/107 | 1/1 | 1.4 @ 17:50 | 20:10 | 49 (19th Street (12), Noe Street (11), Sanchez Street (9), 20th Street (5)) |
| f063_s1_ev | permit_market_one_lane | 307 | 1137 | 12241 | 0 | 19/15 | 0 | 110/107 | 1/1 | 1.4 @ 17:40 | 20:20 | 46 (19th Street (12), Noe Street (11), Sanchez Street (7), Roosevelt Way (4)) |
| f064_s0_ev | permit | 1420 | 1272 | 16055 | 0 | 40/33 | 0 | 121/119 | 1/1 | 6.7 @ 17:30 | 19:20 | 69 (Sanchez Street (13), 19th Street (13), Noe Street (11), 20th Street (8)) |
| f064_s1_ev | permit | 1420 | 1272 | 15983 | 0 | 32/30 | 0 | 121/119 | 1/1 | 7.8 @ 18:00 | 19:10 | 72 (Sanchez Street (13), 19th Street (13), Noe Street (12), 20th Street (8)) |
| f065_s0_ev | permit | 1545 | 935 | 12750 | 0 | 37/15 | 0 | 124/114 | 1/1 | 10.7 @ 13:40 | 18:30 | 114 (19th Street (14), Church Street (13), Sanchez Street (12), Noe Street (12)) |
| f065_s1_ev | permit | 1545 | 935 | 12741 | 0 | 41/9 | 0 | 124/113 | 1/1 | 11.5 @ 13:30 | 18:30 | 121 (Dolores Street (14), Sanchez Street (14), Church Street (14), 19th Street (13)) |
| f066_s0_ev | permit_market_one_lane | 315 | 1298 | 14144 | 0 | 22/20 | 0 | 106/104 | 1/1 | 1.5 @ 13:20 | 20:00 | 51 (Noe Street (12), 19th Street (12), Sanchez Street (9), Roosevelt Way (5)) |
| f066_s1_ev | permit_market_one_lane | 315 | 1298 | 14012 | 0 | 21/21 | 0 | 106/105 | 1/1 | 1.3 @ 13:40 | 19:20 | 51 (Noe Street (12), 19th Street (12), Sanchez Street (9), 20th Street (6)) |
| f067_s0_ev | permit | 2447 | 1199 | 17244 | 0 | 38/28 | 0 | 121/110 | 1/1 | 12.0 @ 18:20 | 20:00 | 133 (19th Street (15), Church Street (15), Dolores Street (15), Sanchez Street (14)) |
| f067_s1_ev | permit | 2447 | 1199 | 17012 | 0 | 22/20 | 0 | 118/109 | 1/1 | 12.1 @ 18:10 | 19:40 | 123 (Church Street (16), Dolores Street (14), Sanchez Street (14), 19th Street (13)) |
| f068_s0_ev | permit | 1022 | 358 | 5675 | 0 | 4/1 | 0 | 112/108 | 0/0 | 5.3 @ 18:10 | 19:20 | 16 (19th Street (8), Noe Street (5), Roosevelt Way (2), Sanchez Street (1)) |
| f068_s1_ev | permit | 1022 | 358 | 5714 | 0 | 5/1 | 0 | 114/109 | 1/0 | 6.6 @ 18:10 | 19:20 | 18 (19th Street (8), Noe Street (5), Roosevelt Way (2), Sanchez Street (1)) |
| f069_s0_ev | permit | 404 | 709 | 7958 | 0 | 9/8 | 0 | 105/103 | 1/1 | 2.9 @ 17:40 | 18:30 | 27 (19th Street (9), Noe Street (7), Sanchez Street (5), Roosevelt Way (4)) |
| f069_s1_ev | permit | 404 | 709 | 8203 | 0 | 12/5 | 0 | 107/103 | 1/1 | 3.7 @ 17:40 | 18:30 | 31 (19th Street (9), Noe Street (7), Sanchez Street (6), Roosevelt Way (4)) |
| f070_s0_ev | permit | 1513 | 888 | 12256 | 0 | 23/21 | 0 | 120/116 | 1/1 | 9.7 @ 17:10 | 18:30 | 123 (19th Street (14), Sanchez Street (14), Dolores Street (13), Church Street (13)) |
| f070_s1_ev | permit | 1513 | 888 | 12316 | 0 | 39/2 | 0 | 120/115 | 1/0 | 10.7 @ 17:00 | 18:30 | 124 (Sanchez Street (14), 19th Street (14), Church Street (14), Dolores Street (13)) |
| f071_s0_ev | permit | 2409 | 1041 | 15332 | 0 | 39/20 | 0 | 117/107 | 1/1 | 15.1 @ 17:20 | 18:40 | 160 (Church Street (21), Dolores Street (17), Sanchez Street (16), 19th Street (15)) |
| f071_s1_ev | permit | 2409 | 1041 | 15540 | 0 | 32/17 | 0 | 117/109 | 1/1 | 16.3 @ 17:30 | 18:30 | 153 (Church Street (19), Dolores Street (16), Sanchez Street (16), 19th Street (16)) |
| f072_s0_ev | permit | 945 | 843 | 10757 | 0 | 12/5 | 0 | 129/126 | 1/0 | 5.8 @ 18:20 | 19:50 | 41 (19th Street (10), Noe Street (9), Sanchez Street (7), Roosevelt Way (4)) |
| f072_s1_ev | permit | 945 | 843 | 10480 | 0 | 10/14 | 0 | 130/127 | 1/1 | 5.1 @ 18:30 | 20:00 | 40 (19th Street (10), Noe Street (8), Sanchez Street (7), Roosevelt Way (4)) |
| f073_s0_ev | permit | 1178 | 1049 | 13255 | 0 | 22/13 | 0 | 123/119 | 1/0 | 5.3 @ 17:20 | 19:30 | 69 (Sanchez Street (14), 19th Street (13), Noe Street (12), Church Street (6)) |
| f073_s1_ev | permit | 1178 | 1049 | 13018 | 0 | 19/8 | 0 | 125/121 | 1/0 | 4.3 @ 11:30 | 19:40 | 67 (Sanchez Street (13), 19th Street (12), Noe Street (11), 20th Street (7)) |
| f074_s0_ev | permit | 2781 | 730 | 12993 | 0 | 27/6 | 0 | 127/115 | 1/0 | 18.4 @ 12:10 | 19:40 | 214 (Church Street (28), Dolores Street (27), Noe Street (17), 19th Street (16)) |
| f074_s1_ev | permit | 2781 | 730 | 12890 | 0 | 34/7 | 0 | 128/114 | 1/1 | 18.8 @ 12:10 | 19:40 | 211 (Dolores Street (28), Church Street (28), Sanchez Street (17), Noe Street (16)) |
| f075_s0_ev | permit | 2741 | 1185 | 17557 | 0 | 43/21 | 0 | 126/114 | 1/1 | 16.3 @ 18:50 | 19:50 | 98 (19th Street (13), Sanchez Street (13), Noe Street (12), Church Street (11)) |
| f075_s1_ev | permit | 2741 | 1185 | 17947 | 0 | 47/45 | 0 | 128/116 | 1/1 | 19.3 @ 18:30 | 19:40 | 101 (Sanchez Street (14), 19th Street (13), Noe Street (12), Church Street (12)) |
| f076_s0_ev | permit_market_open | 1485 | 712 | 10362 | 0 | 27/4 | 0 | 133/126 | 1/1 | 6.4 @ 11:40 | 20:20 | 5 (Market Street (2), Noe Street (2), Roosevelt Way (1)) |
| f076_s1_ev | permit_market_open | 1485 | 712 | 10410 | 0 | 17/13 | 0 | 134/127 | 1/1 | 6.9 @ 11:50 | 20:10 | 6 (Market Street (2), Roosevelt Way (2), Noe Street (2)) |
| f077_s0_ev | permit_market_one_lane | 1749 | 1377 | 17493 | 0 | 60/33 | 0 | 131/119 | 1/1 | 9.6 @ 13:10 | 19:00 | 137 (19th Street (16), Church Street (14), Dolores Street (14), Sanchez Street (14)) |
| f077_s1_ev | permit_market_one_lane | 1749 | 1377 | 17735 | 0 | 68/39 | 1 | 133/119 | 1/1 | 9.6 @ 13:10 | 19:10 | 152 (Dolores Street (17), Church Street (17), 19th Street (16), Sanchez Street (14)) |
| f078_s0_ev | permit | 925 | 1236 | 14538 | 0 | 49/54 | 0 | 122/121 | 1/1 | 4.1 @ 18:00 | 19:10 | 66 (Sanchez Street (13), 19th Street (13), Noe Street (12), 20th Street (7)) |
| f078_s1_ev | permit | 925 | 1236 | 14665 | 0 | 42/29 | 0 | 121/119 | 1/1 | 6.0 @ 11:40 | 19:10 | 64 (Sanchez Street (13), 19th Street (13), Noe Street (12), 20th Street (6)) |
| f079_s0_ev | permit | 2773 | 1220 | 17970 | 0 | 38/35 | 0 | 120/107 | 1/1 | 15.0 @ 17:40 | 18:50 | 221 (Dolores Street (29), Church Street (29), Noe Street (19), Sanchez Street (18)) |
| f079_s1_ev | permit | 2773 | 1220 | 17782 | 0 | 42/33 | 1 | 116/104 | 1/1 | 13.7 @ 17:50 | 19:00 | 201 (Church Street (26), Dolores Street (24), Sanchez Street (16), 19th Street (16)) |
| f080_s0_ev | permit_market_one_lane | 2599 | 871 | 13986 | 0 | 27/14 | 0 | 128/118 | 1/1 | 8.8 @ 12:40 | 20:20 | 113 (Sanchez Street (14), 19th Street (14), Noe Street (13), Church Street (12)) |
| f080_s1_ev | permit_market_one_lane | 2599 | 871 | 14268 | 0 | 33/16 | 0 | 131/119 | 1/1 | 11.7 @ 18:30 | 20:30 | 117 (Sanchez Street (14), Noe Street (13), 19th Street (13), Church Street (13)) |
| f081_s0_ev | permit | 2336 | 882 | 13718 | 0 | 28/10 | 0 | 116/109 | 1/0 | 14.7 @ 18:00 | 19:00 | 120 (Church Street (15), Sanchez Street (14), 19th Street (13), Dolores Street (12)) |
| f081_s1_ev | permit | 2336 | 882 | 13774 | 0 | 35/12 | 0 | 118/110 | 1/1 | 14.0 @ 18:10 | 19:10 | 130 (Dolores Street (16), Church Street (15), Sanchez Street (14), 19th Street (14)) |
| f082_s0_ev | permit | 2456 | 1386 | 19367 | 0 | 51/34 | 0 | 112/106 | 1/1 | 9.4 @ 17:30 | 19:20 | 164 (Church Street (24), Sanchez Street (16), 19th Street (16), Dolores Street (15)) |
| f082_s1_ev | permit | 2456 | 1386 | 19084 | 0 | 63/37 | 0 | 113/105 | 1/1 | 8.2 @ 17:20 | 19:20 | 152 (Church Street (23), 19th Street (16), Dolores Street (15), Noe Street (15)) |
| f083_s0_ev | permit_market_one_lane | 925 | 1210 | 14211 | 0 | 21/25 | 0 | 108/106 | 1/1 | 5.9 @ 18:00 | 19:10 | 55 (Noe Street (12), 19th Street (12), Sanchez Street (10), 20th Street (7)) |
| f083_s1_ev | permit_market_one_lane | 925 | 1210 | 14214 | 0 | 15/33 | 0 | 108/106 | 1/1 | 4.9 @ 18:00 | 19:10 | 55 (Noe Street (12), 19th Street (12), Sanchez Street (10), 20th Street (6)) |
| f084_s0_ev | permit | 1932 | 793 | 12025 | 0 | 21/6 | 0 | 122/118 | 1/1 | 19.5 @ 17:10 | 17:50 | 116 (Sanchez Street (14), Church Street (14), Dolores Street (13), 19th Street (13)) |
| f084_s1_ev | permit | 1932 | 793 | 12096 | 0 | 10/16 | 0 | 121/118 | 1/1 | 18.7 @ 17:10 | 18:00 | 114 (Sanchez Street (14), 19th Street (13), Noe Street (12), Church Street (12)) |
| f085_s0_ev | permit_market_open | 770 | 713 | 8942 | 0 | 14/7 | 0 | 112/105 | 0/0 | 3.2 @ 17:20 | 19:30 | 4 (Market Street (3), Noe Street (1)) |
| f085_s1_ev | permit_market_open | 770 | 713 | 8967 | 0 | 8/2 | 0 | 110/104 | 0/0 | 2.6 @ 18:20 | 19:30 | 5 (Market Street (3), Roosevelt Way (1), Noe Street (1)) |
| f086_s0_ev | permit | 1509 | 380 | 6862 | 0 | 4/7 | 0 | 111/107 | 0/0 | 6.4 @ 17:20 | 18:50 | 53 (Noe Street (12), 19th Street (12), Sanchez Street (8), Church Street (5)) |
| f086_s1_ev | permit | 1509 | 380 | 6854 | 0 | 5/4 | 0 | 111/106 | 0/0 | 5.6 @ 17:20 | 18:50 | 51 (Noe Street (12), 19th Street (12), Sanchez Street (7), Roosevelt Way (4)) |
| f087_s0_ev | permit | 2581 | 1222 | 17675 | 0 | 40/14 | 0 | 114/104 | 1/1 | 15.4 @ 18:20 | 19:20 | 106 (19th Street (15), Sanchez Street (13), Dolores Street (12), Noe Street (12)) |
| f087_s1_ev | permit | 2581 | 1222 | 17608 | 0 | 28/25 | 0 | 112/104 | 1/1 | 15.6 @ 18:10 | 19:20 | 105 (19th Street (15), Sanchez Street (13), Noe Street (12), Dolores Street (10)) |
| f088_s0_ev | permit | 1568 | 718 | 10586 | 0 | 6/6 | 0 | 114/110 | 0/0 | 4.7 @ 18:10 | 20:00 | 54 (19th Street (12), Noe Street (11), Sanchez Street (8), Roosevelt Way (5)) |
| f088_s1_ev | permit | 1568 | 718 | 10525 | 0 | 11/6 | 0 | 115/110 | 1/0 | 4.6 @ 18:10 | 20:10 | 53 (Noe Street (12), 19th Street (12), Sanchez Street (8), 20th Street (5)) |
| f089_s0_ev | permit | 1001 | 1035 | 12680 | 0 | 28/10 | 0 | 120/113 | 1/0 | 3.9 @ 17:50 | 19:30 | 62 (Sanchez Street (13), 19th Street (13), Noe Street (11), 20th Street (6)) |
| f089_s1_ev | permit | 1001 | 1035 | 12705 | 0 | 15/17 | 0 | 120/113 | 1/1 | 4.6 @ 17:30 | 19:30 | 68 (19th Street (13), Noe Street (12), Sanchez Street (10), 20th Street (6)) |
| f090_s0_ev | permit_market_one_lane | 2893 | 1227 | 18424 | 0 | 46/16 | 1 | 135/119 | 1/1 | 23.1 @ 12:00 | 18:40 | 218 (Dolores Street (30), Church Street (28), Noe Street (18), Sanchez Street (17)) |
| f090_s1_ev | permit_market_one_lane | 2893 | 1227 | 18431 | 0 | 57/26 | 0 | 137/120 | 1/1 | 21.8 @ 11:40 | 18:30 | 227 (Church Street (30), Dolores Street (29), Noe Street (18), Sanchez Street (17)) |
| f091_s0_ev | permit | 2636 | 1241 | 17891 | 0 | 38/16 | 0 | 119/111 | 1/1 | 16.1 @ 18:00 | 19:00 | 141 (Church Street (20), 19th Street (15), Noe Street (14), Sanchez Street (14)) |
| f091_s1_ev | permit | 2636 | 1241 | 18104 | 0 | 57/40 | 0 | 120/111 | 1/1 | 17.1 @ 18:00 | 19:00 | 141 (Church Street (23), 19th Street (15), Dolores Street (14), Sanchez Street (14)) |
| f092_s0_ev | permit_market_one_lane | 760 | 1314 | 14984 | 0 | 32/24 | 0 | 111/108 | 1/1 | 3.4 @ 18:50 | 20:10 | 53 (Noe Street (12), 19th Street (12), Sanchez Street (9), 20th Street (6)) |
| f092_s1_ev | permit_market_one_lane | 760 | 1314 | 15067 | 0 | 18/9 | 0 | 109/106 | 1/0 | 3.1 @ 18:20 | 20:20 | 53 (Noe Street (12), 19th Street (12), Sanchez Street (9), 20th Street (6)) |
| f093_s0_ev | permit_market_open | 896 | 1214 | 14364 | 0 | 77/34 | 0 | 141/131 | 1/1 | 6.6 @ 18:10 | 19:40 | 22 (Noe Street (8), Roosevelt Way (4), Market Street (3), Temple Street (2)) |
| f093_s1_ev | permit_market_open | 896 | 1214 | 14324 | 0 | 48/24 | 0 | 138/130 | 1/1 | 6.8 @ 18:00 | 19:50 | 19 (Noe Street (8), Roosevelt Way (4), Market Street (3), Temple Street (2)) |
| f094_s0_ev | permit_market_one_lane | 522 | 1181 | 13428 | 0 | 33/36 | 0 | 119/114 | 1/1 | 3.8 @ 13:40 | 19:50 | 52 (Noe Street (12), 19th Street (12), Sanchez Street (9), 20th Street (6)) |
| f094_s1_ev | permit_market_one_lane | 522 | 1181 | 13281 | 0 | 17/23 | 0 | 118/114 | 1/1 | 3.6 @ 13:30 | 20:00 | 54 (Noe Street (12), 19th Street (12), Sanchez Street (9), Roosevelt Way (5)) |
| f095_s0_ev | permit | 569 | 297 | 4123 | 0 | 5/4 | 0 | 106/105 | 0/0 | 2.7 @ 18:30 | 19:30 | 6 (19th Street (4), Sanchez Street (1), Noe Street (1)) |
| f095_s1_ev | permit | 569 | 297 | 4091 | 0 | 3/3 | 0 | 106/105 | 0/0 | 2.9 @ 18:20 | 19:40 | 0 () |
| f096_s0_ev | permit | 937 | 1155 | 13888 | 0 | 31/23 | 0 | 118/117 | 1/1 | 4.5 @ 16:50 | 18:40 | 73 (Sanchez Street (14), 19th Street (13), Noe Street (12), 20th Street (7)) |
| f096_s1_ev | permit | 937 | 1155 | 13781 | 0 | 40/23 | 0 | 118/117 | 1/1 | 5.4 @ 17:00 | 18:40 | 77 (Sanchez Street (14), Noe Street (12), 19th Street (12), Church Street (6)) |
| f097_s0_ev | permit_market_open | 2059 | 746 | 11842 | 0 | 51/14 | 0 | 138/126 | 1/1 | 11.1 @ 12:30 | 19:50 | 44 (Noe Street (10), Market Street (9), 17th Street (6), Roosevelt Way (4)) |
| f097_s1_ev | permit_market_open | 2059 | 746 | 11642 | 0 | 27/3 | 0 | 137/126 | 1/0 | 9.5 @ 12:10 | 20:00 | 46 (Noe Street (10), Market Street (9), 17th Street (7), Roosevelt Way (4)) |
| f098_s0_ev | permit_market_one_lane | 902 | 1234 | 14433 | 0 | 20/25 | 0 | 116/117 | 1/1 | 3.0 @ 13:40 | 20:20 | 57 (19th Street (13), Noe Street (12), Sanchez Street (10), 20th Street (7)) |
| f098_s1_ev | permit_market_one_lane | 902 | 1234 | 14506 | 0 | 27/20 | 0 | 116/115 | 1/1 | 3.1 @ 13:10 | 20:30 | 57 (Sanchez Street (12), Noe Street (12), 19th Street (12), 20th Street (6)) |
| f099_s0_ev | permit_market_open | 2962 | 1353 | 20031 | 0 | 81/32 | 0 | 143/128 | 1/1 | 21.6 @ 17:30 | 19:00 | 158 (Sanchez Street (20), Church Street (19), Noe Street (18), Market Street (17)) |
| f099_s1_ev | permit_market_open | 2962 | 1353 | 19843 | 0 | 61/33 | 0 | 140/128 | 1/1 | 18.4 @ 17:30 | 19:00 | 159 (Sanchez Street (19), Church Street (18), Noe Street (18), Market Street (16)) |

Boundary effects: the patch is cut at ~700 m; vehicles queue at entry edges when the boundary backs up (visible as depart delay, since SUMO waits to insert). Large event/control gaps in depart delay mean the patch boundary is constraining queues and the radius should grow.
