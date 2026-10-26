import { ActionIcon, Tooltip } from "@mantine/core";
import { useEffect, useRef, useState, type JSX } from "react";

/** A compact, keyboard-accessible question mark for explanatory copy beside a label. */
export function HelpTooltip({ topic, description }: { topic: string; description: string }): JSX.Element {
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [pinned, setPinned] = useState(false);
  const opened = hovered || focused || pinned;

  useEffect(() => {
    if (!opened) return;

    const dismissOnOutsidePointer = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node) || triggerRef.current?.contains(target)) return;
      if (target instanceof Element && target.closest('[role="tooltip"]')) return;
      setHovered(false);
      setFocused(false);
      setPinned(false);
    };
    const dismissOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setHovered(false);
      setFocused(false);
      setPinned(false);
    };

    document.addEventListener("pointerdown", dismissOnOutsidePointer);
    document.addEventListener("keydown", dismissOnEscape);
    return () => {
      document.removeEventListener("pointerdown", dismissOnOutsidePointer);
      document.removeEventListener("keydown", dismissOnEscape);
    };
  }, [opened]);

  return (
    <Tooltip
      opened={opened}
      label={description}
      events={{ hover: false, focus: false, touch: false }}
      multiline
      w="min(320px, calc(100vw - 16px))"
      withArrow
      position="top"
    >
      <ActionIcon
        ref={triggerRef}
        size="xs"
        variant="subtle"
        color="gray"
        style={{ color: "inherit" }}
        aria-label={`About ${topic}`}
        onPointerEnter={(event) => {
          if (event.pointerType !== "touch") setHovered(true);
        }}
        onPointerLeave={() => setHovered(false)}
        onFocus={() => setFocused(true)}
        onBlur={() => {
          setFocused(false);
          setPinned(false);
        }}
        onClick={() => {
          if (pinned) {
            setFocused(false);
            setPinned(false);
          } else {
            setPinned(true);
          }
        }}
      >
        <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" focusable="false">
          <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
          <path
            d="M6.4 6a1.7 1.7 0 1 1 3.1 1c-.6.8-1.5.9-1.5 2.1"
            fill="none"
            stroke="currentColor"
            strokeLinecap="round"
            strokeWidth="1.4"
          />
          <circle cx="8" cy="11.6" r="0.7" fill="currentColor" />
        </svg>
      </ActionIcon>
    </Tooltip>
  );
}
