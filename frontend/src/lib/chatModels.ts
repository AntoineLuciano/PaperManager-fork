import { useEffect, useState } from "react";
import { getMyAiKeyStatus } from "../api/client";
import { fastModelLabel, useInstance } from "./instance";

export type ChatModel = "claude" | "claude-work" | "claude-code" | "litellm";

export const CHAT_MODEL_LABELS: Record<ChatModel, string> = {
  claude: "Claude",
  "claude-work": "Claude (Work)",
  "claude-code": "Claude Code",
  // The "litellm" option is whatever fast model the server set up (Gemma, Haiku, GPT-5 mini...).
  get litellm() { return fastModelLabel(); },
};

type KeyStatus = { claudeCode: boolean; claude: boolean; work: boolean };

// "Claude Code" runs on the server owner's Claude subscription and the backend
// only enables it for users listed in CLAUDE_CODE_USERS, so ask before showing it.
// The Claude options only show when this user has a key for them.
export function useChatModels(): ChatModel[] {
  useInstance(); // re-render once the fast model's name is known
  const [status, setStatus] = useState<KeyStatus | null>(null);
  useEffect(() => {
    getMyAiKeyStatus()
      .then((s) => setStatus({
        claudeCode: Boolean(s.claude_code_available),
        claude: Boolean(s.effective_has_anthropic_api_key),
        work: Boolean(s.effective_has_anthropic_work_api_key),
      }))
      .catch(() => setStatus(null));
  }, []);
  // Until the key status arrives, offer everything so a saved default is not dropped early.
  if (!status) return ["claude-code", "claude", "claude-work", "litellm"];
  const models: ChatModel[] = [];
  if (status.claudeCode) models.push("claude-code");
  if (status.claude) models.push("claude");
  if (status.work) models.push("claude-work");
  models.push("litellm");
  return models;
}
