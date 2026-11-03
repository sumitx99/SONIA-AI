import type { ChatMessage } from "@/lib/api";

export function conversationHistory(messages: ChatMessage[]) {
  const result: { sender: "user" | "bot"; content: string }[] = [];
  let remaining = 24000;
  for (const message of messages.filter(m => !m.error && !m.streaming && m.content.trim()).slice(-20).reverse()) {
    const content = message.content.trim().slice(0, 12000);
    if (content.length > remaining) break;
    result.unshift({ sender: message.sender, content });
    remaining -= content.length;
  }
  while (result.length && result[0].sender !== "user") result.shift();
  return result;
}

/** Editing starts a new continuation at that question; later answers no longer apply. */
export function editConversation(messages: ChatMessage[], messageId: string, content: string) {
  const index = messages.findIndex(message => message.id === messageId && message.sender === "user");
  if (index < 0) throw new Error("This question is no longer available to edit.");
  return { before: messages.slice(0, index), messages: [...messages.slice(0, index), { ...messages[index], content }] };
}
