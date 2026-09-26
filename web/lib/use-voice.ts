'use client';
import { useEffect, useRef, useState } from 'react';
import { sendVoice, voiceNote, type VoiceIntent } from './route.ts';

const MAX_MS = 10_000; // a trip request is a few seconds; stop runaway recordings

/**
 * Tap to talk, tap again to send. Records with MediaRecorder, then api/ /voice (ElevenLabs STT) parses it.
 * `onIntent` returns true when it used the request; otherwise `note` explains what went wrong.
 */
export function useVoice(onIntent: (v: VoiceIntent) => boolean) {
  const [state, setState] = useState<'idle' | 'listening' | 'thinking'>('idle');
  const [note, setNote] = useState('');
  const rec = useRef<MediaRecorder>(undefined);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const onIntentRef = useRef(onIntent);
  onIntentRef.current = onIntent;

  useEffect(() => () => { clearTimeout(timer.current); rec.current?.stream.getTracks().forEach(t => t.stop()); }, []);

  const start = async () => {
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      return setNote('Microphone blocked. Allow it in your browser settings.');
    }
    const r = (rec.current = new MediaRecorder(stream));
    const chunks: Blob[] = [];
    r.ondataavailable = e => chunks.push(e.data);
    r.onstop = async () => {
      clearTimeout(timer.current);
      stream.getTracks().forEach(t => t.stop());
      setState('thinking'); setNote('');
      try {
        const v = await sendVoice(new Blob(chunks, { type: r.mimeType }));
        if (!onIntentRef.current(v)) setNote(voiceNote(v));
      } catch {
        setNote("Couldn't understand that. Try again.");
      } finally {
        setState('idle');
      }
    };
    r.start();
    setState('listening'); setNote('Listening… tap again when done.');
    timer.current = setTimeout(() => r.state === 'recording' && r.stop(), MAX_MS);
  };

  const toggle = () => {
    if (state === 'listening') rec.current?.stop();
    else if (state === 'idle') { setNote(''); start(); }
  };

  return { state, note, toggle };
}
