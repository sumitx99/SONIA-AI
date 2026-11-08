"use client";

import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, type ClipboardEvent, type FormEvent, type KeyboardEvent } from "react";
import { promptSegments, safePromptUrl } from "@/lib/markdown/prompt-links";

function plainText(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? "";
  if (node instanceof HTMLBRElement) return "\n";
  return Array.from(node.childNodes, plainText).join("");
}

function caretOffset(root: HTMLElement): number {
  const selection = window.getSelection();
  if (!selection?.rangeCount || !root.contains(selection.anchorNode)) return plainText(root).length;
  const range = document.createRange();
  range.selectNodeContents(root);
  range.setEnd(selection.anchorNode!, selection.anchorOffset);
  return plainText(range.cloneContents()).length;
}

function pointAtOffset(root: HTMLElement, requestedOffset: number): [Node, number] {
  let remaining = Math.max(0, requestedOffset);
  const visit = (node: Node): [Node, number] | null => {
    if (node.nodeType === Node.TEXT_NODE) {
      const length = node.textContent?.length ?? 0;
      if (remaining <= length) return [node, remaining];
      remaining -= length;
      return null;
    }
    if (node instanceof HTMLBRElement) {
      if (remaining === 0) return [node.parentNode ?? root, Array.prototype.indexOf.call(node.parentNode?.childNodes ?? [], node)];
      remaining -= 1;
      return null;
    }
    for (const child of Array.from(node.childNodes)) {
      const found = visit(child);
      if (found) return found;
    }
    return null;
  };
  return visit(root) ?? [root, root.childNodes.length];
}

function renderLinkedText(root: HTMLElement, value: string, offset: number) {
  const fragment = document.createDocumentFragment();
  const appendText = (text: string) => {
    const lines = text.split("\n");
    lines.forEach((line, index) => {
      if (index) fragment.append(document.createElement("br"));
      if (line) fragment.append(document.createTextNode(line));
    });
  };

  for (const segment of promptSegments(value)) {
    if (!segment.url) {
      appendText(segment.text);
      continue;
    }
    const lines = segment.text.split("\n");
    lines.forEach((line, index) => {
      if (index) fragment.append(document.createElement("br"));
      if (!line) return;
      const link = document.createElement("a");
      link.href = segment.url!;
      link.target = "_blank";
      link.rel = "noopener noreferrer nofollow";
      link.textContent = line;
      link.setAttribute("data-prompt-link", "true");
      fragment.append(link);
    });
  }

  root.replaceChildren(fragment);
  const [node, nodeOffset] = pointAtOffset(root, offset);
  const range = document.createRange();
  range.setStart(node, Math.min(nodeOffset, node.nodeType === Node.TEXT_NODE ? node.textContent?.length ?? 0 : node.childNodes.length));
  range.collapse(true);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
}

function insertPlainText(root: HTMLElement, text: string) {
  const selection = window.getSelection();
  const range = selection?.rangeCount ? selection.getRangeAt(0) : document.createRange();
  if (!root.contains(range.startContainer)) {
    range.selectNodeContents(root);
    range.collapse(false);
  }
  range.deleteContents();
  const fragment = document.createDocumentFragment();
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const inserted: Node[] = [];
  lines.forEach((line, index) => {
    if (index) {
      const br = document.createElement("br");
      fragment.append(br);
      inserted.push(br);
    }
    if (line) {
      const textNode = document.createTextNode(line);
      fragment.append(textNode);
      inserted.push(textNode);
    }
  });
  range.insertNode(fragment);
  const last = inserted[inserted.length - 1];
  if (last) range.setStartAfter(last);
  range.collapse(true);
  selection?.removeAllRanges();
  selection?.addRange(range);
}

type PromptComposerProps = {
  id: string;
  value: string;
  onChange: (value: string) => void;
  onKeyDown: (event: KeyboardEvent<HTMLDivElement>) => void;
  disabled?: boolean;
  placeholder: string;
};

export const PromptComposer = forwardRef<HTMLDivElement, PromptComposerProps>(function PromptComposer({
  id,
  value,
  onChange,
  onKeyDown,
  disabled = false,
  placeholder,
}, forwardedRef) {
  const editor = useRef<HTMLDivElement>(null);
  useImperativeHandle(forwardedRef, () => editor.current!, []);

  const commitEditor = useCallback(() => {
    const root = editor.current;
    if (!root) return;
    const next = plainText(root);
    const offset = caretOffset(root);
    renderLinkedText(root, next, offset);
    onChange(next);
  }, [onChange]);

  useEffect(() => {
    const root = editor.current;
    if (!root || plainText(root) === value) return;
    renderLinkedText(root, value, value.length);
  }, [value]);

  function handleInput(event: FormEvent<HTMLDivElement>) {
    // During IME composition, leave the browser's composing text untouched.
    if ((event.nativeEvent as InputEvent).isComposing) {
      onChange(plainText(event.currentTarget));
      return;
    }
    commitEditor();
  }

  function handlePaste(event: ClipboardEvent<HTMLDivElement>) {
    event.preventDefault();
    const text = event.clipboardData.getData("text/plain");
    insertPlainText(event.currentTarget, text);
    commitEditor();
  }

  function handleCompositionEnd() {
    commitEditor();
  }

  return (
    <div
      ref={editor}
      id={id}
      className="prompt-composer-input"
      role="textbox"
      aria-multiline="true"
      aria-labelledby="question-label"
      aria-disabled={disabled}
      aria-placeholder={placeholder}
      data-placeholder={placeholder}
      contentEditable={!disabled}
      suppressContentEditableWarning
      spellCheck
      onInput={handleInput}
      onPaste={handlePaste}
      onCompositionEnd={handleCompositionEnd}
      onKeyDown={onKeyDown}
      onClick={(event) => {
        const link = (event.target as HTMLElement).closest<HTMLAnchorElement>("a[data-prompt-link]");
        if (!link) return;
        event.preventDefault();
        if (disabled) return;
        const url = safePromptUrl(link.href);
        if (url) window.open(url, "_blank", "noopener,noreferrer");
      }}
    />
  );
});
