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

export function useSettings(): Settings {
  const [settings, setSettings] = useState<Settings>(defaultSettings);

  useEffect(() => {
    const load = () => {
      try {
        const raw = localStorage.getItem(SETTINGS_KEY);
        if (raw) setSettings({ ...defaultSettings, ...JSON.parse(raw) });
      } catch {}
    };

    load();

    window.addEventListener("storage", load);
    return () => window.removeEventListener("storage", load);
  }, []);

  return settings;
}
