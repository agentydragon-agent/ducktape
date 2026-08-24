import type { ChatLaunchOption } from "./client";

/** The rolling-compatible launch catalog: older API replicas omit it entirely. */
export function conversationLaunchOptions(config: {
  chat_launch_options?: ChatLaunchOption[] | null;
}): ChatLaunchOption[] {
  return config.chat_launch_options ?? [];
}

export function launchKey(option: ChatLaunchOption): string {
  return `${option.agent_id}:${option.runtime}`;
}

export function defaultLaunchKey(options: ChatLaunchOption[]): string | null {
  const selected = options.find((option) => option.is_default) ?? options[0];
  return selected ? launchKey(selected) : null;
}

export function shouldShowLaunchSelector(options: ChatLaunchOption[]): boolean {
  return options.length > 1;
}
