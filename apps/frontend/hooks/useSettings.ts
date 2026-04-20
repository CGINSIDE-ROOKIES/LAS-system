"use client";

import { useState, useEffect } from "react";

export interface Settings {
  model: string;
  topK: number;
  answerDetail: string;
  showCitations: boolean;
  showLawGraph: boolean;
  showFollowUpQuestions: boolean;
}

export const SETTINGS_KEY = "legal-ai-settings";

export const defaultSettings: Settings = {
  model: "gemini",
  topK: 5,
  answerDetail: "normal",
  showCitations: true,
  showLawGraph: true,
  showFollowUpQuestions: true,
};

const VALID_TOP_K = [5, 8, 12] as const;
const VALID_ANSWER_DETAIL = ["brief", "normal", "detailed"] as const;

export function normalizeSettings(raw: Partial<Settings>): Settings {
  const merged = { ...defaultSettings, ...raw };
  if (!(VALID_TOP_K as readonly number[]).includes(merged.topK)) {
    merged.topK = defaultSettings.topK;
  }
  if (!(VALID_ANSWER_DETAIL as readonly string[]).includes(merged.answerDetail)) {
    merged.answerDetail = defaultSettings.answerDetail;
  }
  return merged;
}

export function loadSettings(): Settings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (raw) return normalizeSettings(JSON.parse(raw));
  } catch {}
  return { ...defaultSettings };
}

export function saveSettings(settings: Settings): void {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  window.dispatchEvent(new Event("las_settings_changed"));
}

export function useSettings(): Settings {
  const [settings, setSettings] = useState<Settings>(defaultSettings);

  useEffect(() => {
    const load = () => setSettings(loadSettings());
    load();
    window.addEventListener("storage", load);
    window.addEventListener("las_settings_changed", load);
    return () => {
      window.removeEventListener("storage", load);
      window.removeEventListener("las_settings_changed", load);
    };
  }, []);

  return settings;
}
