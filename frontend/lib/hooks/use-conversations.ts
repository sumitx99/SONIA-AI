"use client";

import { useEffect, useRef, useState } from "react";
import { loadConversations, saveConversation, type ChatSession } from "@/lib/api";

// Account-scoped backup protects completed messages if a save fails or a tab reloads.
// Images keep stable IDs; temporary signed URLs are fetched again on display.
function durable(chats: ChatSession[]): ChatSession[] {
  return chats.map((chat) => ({ ...chat, messages: chat.messages.map((message) => ({
    ...message, streaming: false,
    images: message.images?.map((image) => ({ ...image, url: "", source_url: null })),
    web_images: message.web_images?.map((image) => ({ ...image, url: "" })),
  })) }));
}

const fingerprint = (chat: ChatSession) => JSON.stringify({ title: chat.title, messages: durable([chat])[0].messages });

export function useConversations(userId?: string) {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [attempt, retry] = useState(0);
  const saved = useRef(new Map<string, string>());
  const saving = useRef(new Map<string, Promise<void>>());
  const account = useRef(userId);
  account.current = userId;

  useEffect(() => {
    let active = true;
    setLoaded(false);
    setError("");
    setSessions([]);
    saved.current = new Map();
    if (!userId) return;
    const key = `sonia-history:${userId}`;
    let cached: { sessions: ChatSession[]; pendingIds: string[] } = { sessions: [], pendingIds: [] };
    try {
      const parsed = JSON.parse(localStorage.getItem(key) || "null");
      if (Array.isArray(parsed?.sessions) && Array.isArray(parsed?.pendingIds)) cached = parsed;
    } catch { /* Storage may be disabled. Server history still works. */ }
    setSessions(cached.sessions);
    loadConversations(userId).then((remote) => {
      if (!active) return;
      saved.current = new Map(remote.map((chat) => [chat.id, fingerprint(chat)]));
      const combined = new Map(remote.map((chat) => [chat.id, chat]));
      for (const chat of cached.sessions) {
        if (cached.pendingIds.includes(chat.id)) combined.set(chat.id, chat);
      }
      setSessions([...combined.values()]);
    }).catch(() => {
      if (active) setError("Account history could not be loaded. Your local backup is available; retry to reconnect.");
    }).finally(() => { if (active) setLoaded(true); });
    return () => { active = false; };
  }, [userId, attempt]);

  useEffect(() => {
    if (!userId || !loaded) return;
    const pendingIds = sessions.filter((chat) => saved.current.get(chat.id) !== fingerprint(chat)).map((chat) => chat.id);
    try {
      localStorage.setItem(`sonia-history:${userId}`, JSON.stringify({ sessions: durable(sessions), pendingIds }));
    } catch { /* A full/disabled browser cache must not prevent server saves. */ }
    const timer = setTimeout(() => {
      for (const chat of sessions) {
        if (chat.messages.some((message) => message.streaming)) continue;
        const value = fingerprint(chat);
        if (saved.current.get(chat.id) === value) continue;
        // Preserve request order for successive snapshots of the same conversation.
        const previous = saving.current.get(chat.id) || Promise.resolve();
        const write = previous.catch(() => {}).then(async () => {
          if (account.current !== userId) return;
          await saveConversation(chat, userId);
          if (account.current === userId) {
            saved.current.set(chat.id, value);
            try {
              const key = `sonia-history:${userId}`;
              const cache = JSON.parse(localStorage.getItem(key) || "null");
              const cached = cache?.sessions?.find((item: ChatSession) => item.id === chat.id);
              if (cached && fingerprint(cached) === value) {
                cache.pendingIds = cache.pendingIds.filter((id: string) => id !== chat.id);
                localStorage.setItem(key, JSON.stringify(cache));
              }
            } catch { /* Account save already succeeded. */ }
          }
        }).catch(() => {
          if (account.current === userId) setError("Changes are backed up on this device, but account sync failed. Retry to reconnect.");
        });
        saving.current.set(chat.id, write);
      }
    }, 400);
    return () => clearTimeout(timer);
  }, [sessions, userId, loaded]);

  return { sessions, setSessions, loaded, error, setError, retry: () => retry((value) => value + 1) };
}
