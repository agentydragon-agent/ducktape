import { Code, Group, Text } from "@mantine/core";
import type { JSX, ReactNode } from "react";

/** Unclamped chips: compact may approve the call, so no value may be elided by CSS. */
export function Chip({ label, value }: { label: string; value: ReactNode }): JSX.Element {
  return (
    <Code style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>
      {label}: {value}
    </Code>
  );
}

export function CompactCall({ operation, children }: { operation: string; children: ReactNode }): JSX.Element {
  return (
    <Group gap={4} align="center" wrap="wrap">
      <Text component="span" size="sm">
        {operation}
      </Text>
      {children}
    </Group>
  );
}
