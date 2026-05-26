"use client";

import Link from "next/link";
import { useEffect, useState, Fragment } from "react";
import {
  FilePen, Clock, Check, ArrowRight,
  Search, Bell, TrendingUp, Newspaper, Loader2,
} from "lucide-react";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/AppSidebar";
import { getHistory, type HistoryItem } from "@/lib/api-client";
import { format, isToday, isYesterday } from "date-fns";
import { ko } from "date-fns/locale";

// ─── 디자인 토큰 ─────────────────────────────────────────────────────────────

const T = {
  bgApp:        "#FFFFFF",
  bgCanvas:     "#FAFAFA",
  bgCard:       "#FFFFFF",
  bgCardSoft:   "#F5F7FA",
  bgSb:         "#14182A",
  primary:      "#3D52F5",
  primary700:   "#2C3DCF",
  primary50:    "#ECEFFE",
  primary100:   "#DBE0FD",
  warm:         "#EE8A5D",
  warmSoft:     "#FCEAE0",
  warmDeep:     "#C76844",
  green:        "#2D9C73",
  greenSoft:    "#DDF1E7",
  amber:        "#E0A43A",
  amberSoft:    "#FBEDC9",
  amberInk:     "#8A6312",
  rose:         "#D9484A",
  roseSoft:     "#FCE2E1",
  ink900:       "#14182A",
  ink800:       "#1F2438",
  ink700:       "#2A2F44",
  ink500:       "#5C6275",
  ink400:       "#8087A0",
  ink300:       "#B6BCCB",
  ink200:       "#E2E5ED",
  border:       "#E5E9F5",
  borderSoft:   "#EDF0F7",
  borderStrong: "#D5DCF0",
  sbText:       "rgba(255,255,255,.72)",
  sbTextDim:    "rgba(255,255,255,.48)",
  sbStrong:     "#FFFFFF",
  sbBorder:     "rgba(255,255,255,.07)",
  sbActive:     "rgba(255,255,255,.09)",
  shadowCard:   "0 1px 0 rgba(20,24,42,.04),0 1px 2px rgba(20,24,42,.04)",
} as const;

// ─── 목데이터 ─────────────────────────────────────────────────────────────────

const MOCK_USER = { name: "씨지인사이드", initial: "C", dept: "경영지원본부 · 법무팀" };


const DRAFTS = [
  { id: 1, title: "(주)그린로지스 - 운송 위·수탁 계약서", step: "2/4 단계 · 대금/지급", updated: "10분 전", progress: 52 },
  { id: 2, title: "경력직 채용 표준 근로계약서 v3",       step: "3/4 단계 · 휴가·휴직", updated: "어제",    progress: 78 },
];

const NOTICES = [
  { id: 1, tag: "업데이트",    title: "중대재해처벌법 시행령 개정사항이 반영되었습니다", when: "1일 전" },
  { id: 2, tag: "신규 템플릿", title: "스타트업 투자계약서(SAFE) 표준 양식 추가",        when: "3일 전" },
];

const USAGE = {
  used: 101, quota: 500, deltaPct: 12, period: "5월 1일 ~ 8일",
  breakdown: [
    { key: "qna",    label: "법령 Q&A",   value: 84, color: T.primary },
    { key: "review", label: "계약서 검토", value: 11, color: T.green   },
    { key: "draft",  label: "초안 작성",   value: 6,  color: T.amber   },
  ],
};

const HERO_METRICS = [
  { k: "커버리지",    v: "8개 법령" },
  { k: "표준 템플릿", v: "32개"      },
  { k: "평균 응답",   v: "2.4초"     },
  { k: "평균 검토",   v: "30초"      },
];

type Illust = "qna" | "review" | "draft";

const FEATURES: {
  num: string; title: string; tagline: string; desc: string;
  bullets: string[]; cta: string; accent: string; bg: string;
  illust: Illust; stat: { k: string; v: string } | null; example: string; href: string;
}[] = [
  {
    num: "01", title: "법령 Q&A", tagline: "법령을 친구처럼 물어보기",
    desc: "근로기준법, 하도급법, 건설산업기본법 등 8개 법령의 조문과 판례 기반 답변.",
    bullets: ["근거 조문 자동 인용", "관련 판례 함께 보기", "대화 히스토리 저장"],
    cta: "질문 시작", accent: T.primary, bg: T.primary50, illust: "qna",
    stat: null, example: "연차수당 계산 기준이 뭐야?", href: "/chat",
  },
  {
    num: "02", title: "계약서 검토", tagline: "놓친 위험을 30초 만에",
    desc: "PDF · DOCX를 올리면 위험 조항을 자동 진단하고 수정 문구를 제안해드려요.",
    bullets: ["42종 리스크 룰셋", "조항별 비교 뷰", "협상 포인트 정리"],
    cta: "계약서 업로드", accent: T.green, bg: T.greenSoft, illust: "review",
    stat: { k: "이번 주 검토", v: "11건" }, example: "NDA · 디자인스튜디오 코코넛", href: "/contract-review",
  },
  {
    num: "03", title: "계약서 초안 작성", tagline: "빈 화면이 두렵지 않게",
    desc: "용도와 조건만 입력하세요. 표준 양식과 추천 조항으로 초안이 완성됩니다.",
    bullets: ["32종 표준 템플릿", "단계별 가이드", "동료와 공유·협업"],
    cta: "초안 만들기", accent: T.amberInk, bg: T.amberSoft, illust: "draft",
    stat: { k: "이번 주 작성", v: "6건" }, example: "운송 위·수탁 계약서", href: "/contract-draft",
  },
];

const PILL_TONE: Record<string, { bg: string; border: string; color: string }> = {
  primary: { bg: T.primary50,  border: T.primary100, color: T.primary700 },
  warm:    { bg: T.warmSoft,   border: T.warmSoft,   color: T.warmDeep  },
  green:   { bg: T.greenSoft,  border: T.greenSoft,  color: T.green     },
  amber:   { bg: T.amberSoft,  border: T.amberSoft,  color: T.amberInk  },
  rose:    { bg: T.roseSoft,   border: T.roseSoft,   color: T.rose      },
};

// ─── 공통 컴포넌트 ────────────────────────────────────────────────────────────

function Pill({
  children, tone, style,
}: {
  children: React.ReactNode;
  tone?: string;
  style?: React.CSSProperties;
}) {
  const c = tone && PILL_TONE[tone]
    ? PILL_TONE[tone]
    : { bg: T.bgCardSoft, border: T.border, color: T.ink700 };
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 6,
      padding: "4px 10px", borderRadius: 999,
      fontSize: 12, fontWeight: 500,
      background: c.bg, border: `1px solid ${c.border}`, color: c.color,
      ...style,
    }}>{children}</span>
  );
}

function SectionHead({
  icon, title, sub, action,
}: {
  icon: React.ReactNode; title: string; sub?: string; action?: React.ReactNode;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <span style={{
        width: 28, height: 28, borderRadius: 8,
        background: T.bgCardSoft, color: T.ink500,
        display: "flex", alignItems: "center", justifyContent: "center",
      }}>{icon}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: T.ink900, letterSpacing: "-.005em" }}>{title}</div>
        {sub && <div style={{ fontSize: 11.5, color: T.ink500, marginTop: 1 }}>{sub}</div>}
      </div>
      {action}
    </div>
  );
}

// ─── 사이드바 ─────────────────────────────────────────────────────────────────

// 텍스트를 opacity+maxWidth로 부드럽게 fade 처리하는 헬퍼

// ─── 탑바 ────────────────────────────────────────────────────────────────────

function TopBar() {
  return (
    <header style={{
      display: "flex", alignItems: "center", gap: 16,
      padding: "18px 24px 18px 12px", borderBottom: `1px solid ${T.border}`,
      background: T.bgCanvas, position: "sticky", top: 0, zIndex: 5,
    }}>
      <SidebarTrigger
        style={{
          width: 32, height: 32, borderRadius: 8, flexShrink: 0,
          border: `1px solid ${T.border}`, color: T.ink400,
        }}
      />
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 12, color: T.ink500, fontWeight: 500 }}>대시보드</div>
        <div style={{ fontSize: 16, color: T.ink900, fontWeight: 700, letterSpacing: "-.01em" }}>홈</div>
      </div>
      <div style={{ flex: 1, maxWidth: 520, marginLeft: 24, position: "relative" }}>
        <Search size={16} style={{
          position: "absolute", left: 14, top: "50%", transform: "translateY(-50%)", color: T.ink400,
        }} />
        <input
          placeholder="법령, 판례, 계약 조항을 검색해보세요"
          style={{
            width: "100%", height: 40, padding: "0 40px 0 38px",
            border: `1px solid ${T.border}`, borderRadius: 10,
            background: T.bgCardSoft, color: T.ink900,
            fontFamily: "inherit", fontSize: 14, outline: "none",
          }}
        />
        <kbd style={{
          position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)",
          fontSize: 10.5, color: T.ink500, background: T.bgCard,
          border: `1px solid ${T.border}`, borderRadius: 6, padding: "3px 6px",
          fontFamily: "monospace",
        }}>⌘ K</kbd>
      </div>
      <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
        <button type="button" style={{
          display: "inline-flex", alignItems: "center", gap: 6, padding: "6px 10px",
          borderRadius: 8, border: `1px solid ${T.border}`,
          background: "transparent", color: T.ink700, cursor: "pointer", fontSize: 12.5,
          fontFamily: "inherit",
        }}>
          <Bell size={16} />
          <span style={{ width: 8, height: 8, borderRadius: 99, background: T.primary, marginLeft: -2 }} />
        </button>
        <button type="button" style={{
          display: "inline-flex", alignItems: "center", padding: "6px 10px",
          borderRadius: 8, border: `1px solid ${T.border}`,
          background: "transparent", color: T.ink700, cursor: "pointer", fontSize: 12.5,
          fontFamily: "inherit",
        }}>도움말</button>
      </div>
    </header>
  );
}

// ─── 히어로 ───────────────────────────────────────────────────────────────────

function HeroDecoration() {
  return (
    <svg width="160" height="160" viewBox="0 0 320 320"
      style={{ position: "absolute", right: -30, top: -40, opacity: 0.35, pointerEvents: "none" }}>
      <circle cx="160" cy="160" r="140" fill="none" stroke={T.primary} strokeWidth="1.2" strokeDasharray="2 6" />
      <circle cx="160" cy="160" r="100" fill="none" stroke={T.primary} strokeWidth="1.2" />
      <circle cx="160" cy="160" r="60"  fill={T.primary} opacity={0.18} />
      <g transform="translate(140 140)" stroke={T.primary700} strokeWidth="1.6" fill="none" strokeLinecap="round">
        <path d="M20 0v40" /><path d="M5 8h30" />
        <path d="M5 8l-7 16a8 8 0 0 0 14 0z" />
        <path d="M35 8l-7 16a8 8 0 0 0 14 0z" />
        <path d="M12 44h16" />
      </g>
    </svg>
  );
}

function Hero() {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const raf = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <section style={{
      position: "relative", overflow: "hidden", borderRadius: 20,
      background: "linear-gradient(180deg,#EEF2FF 0%,#FAFBFF 100%)",
      border: "1px solid #D4DEFF", padding: "24px 44px 20px",
      opacity: mounted ? 1 : 0,
      transform: mounted ? "translateY(0)" : "translateY(18px)",
      transition: "opacity .55s cubic-bezier(.4,0,.2,1), transform .55s cubic-bezier(.4,0,.2,1)",
    }}>
      <HeroDecoration />
      <div style={{ position: "relative", maxWidth: 760 }}>
        <h1 style={{
          fontSize: 26, fontWeight: 800, color: T.ink900,
          letterSpacing: "-.025em", lineHeight: 1.25, margin: 0,
        }}>
          안녕하세요 씨지인사이드 님,{" "}
          <span style={{ color: T.primary700 }}>오늘 업무</span>도 같이 정리해볼까요?
        </h1>
        <p style={{ fontSize: 13, color: T.ink500, marginTop: 10, lineHeight: 1.5 }}>
          법령 Q&amp;A · 계약서 검토 · 초안 작성 — 조문과 판례를 근거로 바로 정리해드려요.
        </p>
        <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
          {HERO_METRICS.map((m, i) => (
            <Fragment key={m.k}>
              {i > 0 && <span style={{ width: 1, height: 14, background: "rgba(20,24,42,.10)" }} />}
              <div style={{ display: "flex", alignItems: "baseline", gap: 5 }}>
                <span style={{ fontSize: 10, color: T.ink400, fontWeight: 500 }}>{m.k}</span>
                <span style={{ fontSize: 12.5, fontWeight: 700, color: T.ink900, letterSpacing: "-.02em" }}>{m.v}</span>
              </div>
            </Fragment>
          ))}
        </div>
      </div>
    </section>
  );
}

// ─── 기능 카드 일러스트 ───────────────────────────────────────────────────────

function IllustQnA({ accent }: { accent: string }) {
  return (
    <svg width="100%" height="100%" viewBox="0 0 280 96" preserveAspectRatio="xMidYMid slice">
      {/* 질문 말풍선 (좌상단) */}
      <rect x="14" y="10" width="122" height="40" rx="13" fill={accent} opacity={0.13} />
      {/* 질문 텍스트 라인 */}
      <rect x="26" y="23" width="66" height="5" rx="2.5" fill={accent} opacity={0.3} />
      <rect x="26" y="34" width="46" height="5" rx="2.5" fill={accent} opacity={0.18} />
      {/* 답변 말풍선 (우하단) */}
      <rect x="96" y="46" width="120" height="38" rx="13" fill={accent} opacity={0.18} />
      {/* 답변 텍스트 라인 */}
      <rect x="108" y="57" width="64" height="4" rx="2" fill={accent} opacity={0.35} />
      <rect x="108" y="68" width="44" height="4" rx="2" fill={accent} opacity={0.22} />
      {/* 우측 상단 액센트 */}
      <circle cx="248" cy="20" r="13" fill={accent} opacity={0.4} />
      <path d="M244 16l6 4-6 4" stroke="#fff" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function IllustReview({ accent }: { accent: string }) {
  return (
    <svg width="100%" height="100%" viewBox="0 0 280 96" preserveAspectRatio="xMidYMid slice">
      <rect x="100" y="14" width="100" height="68" rx="6" fill="#fff" stroke={accent} strokeOpacity={0.5} />
      <rect x="110" y="24" width="80" height="4" rx="2" fill={accent} opacity={0.5} />
      <rect x="110" y="34" width="60" height="4" rx="2" fill={accent} opacity={0.25} />
      <rect x="110" y="44" width="70" height="4" rx="2" fill={accent} opacity={0.25} />
      <rect x="110" y="54" width="40" height="4" rx="2" fill="#D9484A" opacity={0.7} />
      <rect x="110" y="64" width="55" height="4" rx="2" fill={accent} opacity={0.25} />
      <circle cx="218" cy="56" r="14" fill={accent} />
      <path d="M212 56l4 4 8-8" stroke="#fff" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function IllustDraft({ accent }: { accent: string }) {
  return (
    <svg width="100%" height="100%" viewBox="0 0 280 96" preserveAspectRatio="xMidYMid slice">
      <rect x="80" y="12" width="120" height="72" rx="6" fill="#fff" stroke={accent} strokeOpacity={0.5} />
      <rect x="90" y="22" width="50" height="4"  rx="2"   fill={accent} opacity={0.55} />
      <rect x="90" y="32" width="100" height="3" rx="1.5" fill={accent} opacity={0.18} />
      <rect x="90" y="40" width="80"  height="3" rx="1.5" fill={accent} opacity={0.18} />
      <rect x="90" y="48" width="90"  height="3" rx="1.5" fill={accent} opacity={0.18} />
      <rect x="90" y="60" width="50"  height="14" rx="3"  fill={accent} opacity={0.5}  />
      <g transform="translate(195 60)">
        <path d="M0 14 L18 -4 L24 2 L6 20 Z" fill={accent} />
        <path d="M0 14 L0 22 L8 20 Z" fill={accent} opacity={0.7} />
      </g>
    </svg>
  );
}

// ─── 기능 카드 ────────────────────────────────────────────────────────────────

function FeatureCard({ num, title, tagline, desc, bullets, cta, accent, bg, illust, stat, example, href }: typeof FEATURES[0]) {
  return (
    <div style={{
      background: T.bgCard, border: `1px solid ${T.border}`,
      borderRadius: 18, padding: 22,
      display: "flex", flexDirection: "column", gap: 12,
      position: "relative", overflow: "hidden",
      boxShadow: T.shadowCard,
    }}>
      {/* 일러스트 블록 */}
      <div style={{ height: 96, borderRadius: 12, background: bg, position: "relative", overflow: "hidden", marginBottom: 4 }}>
        {illust === "qna"    && <IllustQnA    accent={accent} />}
        {illust === "review" && <IllustReview accent={accent} />}
        {illust === "draft"  && <IllustDraft  accent={accent} />}
        <span style={{
          position: "absolute", top: 10, left: 12,
          fontSize: 11, fontWeight: 700, color: accent,
          fontFamily: "monospace", letterSpacing: ".05em",
        }}>{num}</span>
        {stat && (
          <span style={{
            position: "absolute", top: 10, right: 12,
            display: "inline-flex", alignItems: "center", gap: 4,
            padding: "3px 8px", borderRadius: 999,
            background: "rgba(255,255,255,.85)",
            fontSize: 10.5, fontWeight: 600, color: accent,
            backdropFilter: "blur(4px)",
          }}>
            <span style={{ width: 5, height: 5, borderRadius: 99, background: accent }} />
            {stat.k} {stat.v}
          </span>
        )}
      </div>

      {/* 텍스트 */}
      <div>
        <h3 style={{ fontSize: 18, fontWeight: 700, color: T.ink900, letterSpacing: "-.015em" }}>{title}</h3>
        <div style={{ fontSize: 12.5, color: accent, fontWeight: 600, marginTop: 2 }}>{tagline}</div>
        <p style={{ fontSize: 13, color: T.ink500, lineHeight: 1.55, marginTop: 8 }}>{desc}</p>
      </div>

      {/* 불릿 */}
      <ul style={{ display: "flex", flexDirection: "column", gap: 6, paddingTop: 4, listStyle: "none", padding: 0, margin: 0 }}>
        {bullets.map(b => (
          <li key={b} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5, color: T.ink700 }}>
            <span style={{
              width: 16, height: 16, borderRadius: 99, background: bg, color: accent, flexShrink: 0,
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              <Check size={10} strokeWidth={2.4} />
            </span>
            {b}
          </li>
        ))}
      </ul>

      {/* 예시 */}
      <div style={{
        marginTop: 4, padding: "10px 12px", background: bg, borderRadius: 10,
        display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: T.ink700,
      }}>
        <span style={{ fontSize: 10.5, fontWeight: 700, color: accent, textTransform: "uppercase", letterSpacing: ".06em", flexShrink: 0 }}>예시</span>
        <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{example}</span>
      </div>

      {/* CTA */}
      <Link href={href} style={{
        marginTop: "auto", alignSelf: "stretch",
        display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
        padding: "12px 20px", borderRadius: 12,
        background: accent, color: "#fff",
        fontSize: 14, fontWeight: 700, textDecoration: "none",
        boxShadow: `0 2px 8px ${accent}55`,
      }}>
        {cta} <ArrowRight size={15} />
      </Link>
    </div>
  );
}

function FeatureCards() {
  return (
    <section>
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginBottom: 18, gap: 16 }}>
        <div>
          <h2 style={{ fontSize: 22, fontWeight: 700, color: T.ink900, letterSpacing: "-.015em" }}>무엇을 도와드릴까요?</h2>
          <p style={{ fontSize: 13, color: T.ink500, marginTop: 4 }}>세 가지 기능을 선택하면 각각의 작업 페이지로 이어져요.</p>
        </div>
        <Pill tone="primary" style={{ fontSize: 11.5, flexShrink: 0 }}>이번 주 인기 · 법령 Q&A</Pill>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 16 }}>
        {FEATURES.map(f => <FeatureCard key={f.num} {...f} />)}
      </div>
    </section>
  );
}

// ─── 위젯들 ───────────────────────────────────────────────────────────────────

const LAW_ABBREV: Record<string, string> = {
  "기간제 및 단시간근로자 보호 등에 관한 법률": "기간제법",
  "파견근로자 보호 등에 관한 법률": "파견근로자법",
  "근로자퇴직급여 보장법": "퇴직급여법",
  "남녀고용평등과 일·가정 양립 지원에 관한 법률": "남녀고용평등법",
  "하도급거래 공정화에 관한 법률": "하도급법",
};

function formatWhen(dateStr: string): string {
  const d = new Date(dateStr);
  if (isToday(d)) return format(d, "HH:mm");
  if (isYesterday(d)) return "어제";
  return format(d, "M월 d일", { locale: ko });
}

function getLawTag(item: HistoryItem): string | null {
  const src = item.sources.find((s) => s.doc_type === "law" && s.law_name);
  if (!src) return null;
  const name = src.law_name;
  return LAW_ABBREV[name] ?? (name.length > 7 ? name.slice(0, 7) + "…" : name);
}

type SessionThread = {
  id: string;
  title: string;
  count: number;
  lastDate: string;
  lastLawTag: string | null;
};

function groupToThreads(items: HistoryItem[]): SessionThread[] {
  const sessionMap = new Map<string, HistoryItem[]>();
  const orphans: HistoryItem[] = [];

  for (const item of items) {
    if (item.session_id) {
      if (!sessionMap.has(item.session_id)) sessionMap.set(item.session_id, []);
      sessionMap.get(item.session_id)!.push(item);
    } else {
      orphans.push(item);
    }
  }

  const threads: SessionThread[] = [];

  for (const [sid, sessionItems] of sessionMap) {
    const sorted = [...sessionItems].sort(
      (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    );
    const last = sorted[sorted.length - 1];
    threads.push({
      id: sid,
      title: sorted[0].question,
      count: sorted.length,
      lastDate: last.created_at,
      lastLawTag: getLawTag(last),
    });
  }

  for (const item of orphans) {
    threads.push({
      id: item.id,
      title: item.question,
      count: 1,
      lastDate: item.created_at,
      lastLawTag: getLawTag(item),
    });
  }

  return threads.sort(
    (a, b) => new Date(b.lastDate).getTime() - new Date(a.lastDate).getTime()
  );
}

function HistoryWidget() {
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [threads, setThreads] = useState<SessionThread[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    getHistory({ limit: 30 })
      .then((r) => setThreads(groupToThreads(r.items).slice(0, 3)))
      .catch(console.error)
      .finally(() => setIsLoading(false));
  }, []);

  return (
    <div style={{
      background: T.bgCard,
      border: `1px solid ${T.border}`,
      borderLeft: `4px solid rgba(61,82,245,0.18)`,
      borderRadius: 16, padding: 24, boxShadow: T.shadowCard,
    }}>
      <SectionHead
        icon={<Clock size={16} />}
        title="이어서 대화하기"
        sub="최근 법령 Q&A"
        action={
          <Link href="/conversations" style={{
            display: "inline-flex", alignItems: "center", gap: 6, padding: "6px 10px",
            borderRadius: 8, border: `1px solid ${T.primary100}`,
            background: T.primary50, color: T.primary700, fontSize: 12.5,
            fontWeight: 600, textDecoration: "none",
          }}>전체 →</Link>
        }
      />
      {isLoading ? (
        <div style={{ display: "flex", justifyContent: "center", paddingTop: 24 }}>
          <Loader2 size={18} color={T.ink400} className="animate-spin" />
        </div>
      ) : threads.length === 0 ? (
        <p style={{ marginTop: 16, fontSize: 13, color: T.ink400, textAlign: "center" }}>아직 대화 내역이 없어요.</p>
      ) : (
        <ul style={{ marginTop: 8, listStyle: "none", padding: 0, margin: 0 }}>
          {threads.map((h, i) => (
              <li key={h.id} style={{ borderTop: i === 0 ? "none" : `1px solid ${T.borderSoft}` }}>
                <Link
                  href={`/conversations?thread=${h.id}`}
                  onMouseEnter={() => setHoveredId(h.id)}
                  onMouseLeave={() => setHoveredId(null)}
                  style={{
                    padding: "11px 10px",
                    marginLeft: -10, marginRight: -10,
                    borderRadius: 8,
                    display: "flex", alignItems: "flex-start", gap: 12,
                    background: hoveredId === h.id ? T.bgCardSoft : "transparent",
                    textDecoration: "none",
                    transition: "background .12s ease",
                  }}
                >
                  <span style={{ fontSize: 11, color: T.ink400, fontFamily: "monospace", marginTop: 2, minWidth: 24 }}>
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{
                      fontSize: 13.5, color: T.ink900, fontWeight: 500, lineHeight: 1.4,
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}>{h.title}</div>
                    <div style={{ marginTop: 4, display: "flex", alignItems: "center", gap: 8 }}>
                      {h.lastLawTag && <Pill tone="primary" style={{ fontSize: 10.5 }}>{h.lastLawTag}</Pill>}
                      {h.count > 1 && (
                        <span style={{ fontSize: 10.5, color: T.ink400 }}>{h.count}개 질문 ·</span>
                      )}
                      <span style={{ fontSize: 11.5, color: T.ink400 }}>{formatWhen(h.lastDate)}</span>
                    </div>
                  </div>
                  <ArrowRight
                    size={14}
                    color={hoveredId === h.id ? T.primary : T.ink300}
                    style={{ marginTop: 4, flexShrink: 0, transition: "color .12s ease" }}
                  />
                </Link>
              </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function DraftsWidget() {
  const [hoveredId, setHoveredId] = useState<number | null>(null);

  return (
    <div style={{
      background: T.bgCard,
      border: `1px solid ${T.border}`,
      borderLeft: `4px solid rgba(224,164,58,0.22)`,
      borderRadius: 16, padding: 24, boxShadow: T.shadowCard,
    }}>
      <SectionHead icon={<FilePen size={16} />} title="작성 중인 초안" sub="자동 저장됨" />
      <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8 }}>
        {DRAFTS.map(d => (
          <a
            key={d.id}
            href="/contract-draft"
            onMouseEnter={() => setHoveredId(d.id)}
            onMouseLeave={() => setHoveredId(null)}
            style={{
              display: "block", padding: 12, borderRadius: 10,
              background: hoveredId === d.id ? T.amberSoft : T.bgCardSoft,
              border: `1px dashed ${hoveredId === d.id ? T.amber : T.borderStrong}`,
              textDecoration: "none",
              transition: "background .12s ease, border-color .12s ease",
            }}
          >
            <div style={{ fontSize: 13, fontWeight: 600, color: T.ink900, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{d.title}</div>
            <div style={{ fontSize: 11.5, color: T.ink500, marginTop: 4 }}>{d.step} · {d.updated}</div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8 }}>
              <div style={{ flex: 1, height: 4, background: T.ink200, borderRadius: 99, overflow: "hidden" }}>
                <div style={{ width: `${d.progress}%`, height: "100%", background: T.amber }} />
              </div>
              <span style={{ fontSize: 11.5, fontWeight: 600, color: T.amberInk, display: "flex", alignItems: "center", gap: 3 }}>
                이어쓰기 <ArrowRight size={12} />
              </span>
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}

function UsageWidget() {
  const u = USAGE;
  return (
    <div style={{
      background: T.bgCardSoft,
      border: `1px solid ${T.borderSoft}`, borderRadius: 16, padding: 24,
      boxShadow: T.shadowCard,
    }}>
      <SectionHead icon={<TrendingUp size={16} />} title="이번 달 사용량" sub={u.period} />
      <div style={{ marginTop: 14, display: "flex", alignItems: "baseline", gap: 6 }}>
        <span style={{ fontSize: 30, fontWeight: 700, color: T.ink900, letterSpacing: "-.02em" }}>{u.used}</span>
        <span style={{ fontSize: 13, color: T.ink500, fontWeight: 500 }}>/ {u.quota} 건</span>
        <span style={{ marginLeft: "auto", fontSize: 11, color: T.green, fontWeight: 600 }}>↗ +{u.deltaPct}%</span>
      </div>
      <div style={{ height: 6, background: T.ink200, borderRadius: 99, overflow: "hidden", marginTop: 10 }}>
        <div style={{ display: "flex", height: "100%" }}>
          {u.breakdown.map(b => (
            <div key={b.key} style={{ width: `${(b.value / u.quota) * 100}%`, background: b.color }} />
          ))}
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 10, marginTop: 14 }}>
        {u.breakdown.map(b => (
          <div key={b.key} style={{ borderTop: `2px solid ${b.color}`, paddingTop: 8 }}>
            <div style={{ fontSize: 11, color: T.ink500, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{b.label}</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: T.ink900, marginTop: 2, letterSpacing: "-.02em" }}>
              {b.value}<span style={{ fontSize: 11, color: T.ink500, fontWeight: 500 }}> 건</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function NoticesWidget() {
  return (
    <div style={{
      background: "transparent",
      border: `1px solid ${T.borderSoft}`,
      borderRadius: 16, padding: "14px 18px",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
        <Newspaper size={13} color={T.ink400} />
        <span style={{ fontSize: 12, fontWeight: 600, color: T.ink500, letterSpacing: "-.005em" }}>공지사항</span>
      </div>
      <ul style={{ marginTop: 6, listStyle: "none", padding: 0 }}>
        {NOTICES.map((n, i) => (
          <li key={n.id} style={{ padding: "8px 0", borderTop: i === 0 ? "none" : `1px solid ${T.borderSoft}` }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <Pill tone="warm" style={{ fontSize: 10.5 }}>{n.tag}</Pill>
              <span style={{ marginLeft: "auto", fontSize: 10.5, color: T.ink400 }}>{n.when}</span>
            </div>
            <div style={{ fontSize: 12, color: T.ink700, marginTop: 5, lineHeight: 1.5 }}>{n.title}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ─── 메인 ─────────────────────────────────────────────────────────────────────

export default function Dashboard() {
  return (
    <SidebarProvider>
    <div style={{
      width: "100%", height: "100vh", display: "flex",
      background: T.bgApp, overflow: "hidden",
      fontFamily: '"Pretendard","Pretendard Variable",-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR",system-ui,sans-serif',
      color: T.ink800, fontSize: 14, lineHeight: 1.45,
      letterSpacing: "-.005em",
    }}>
      <AppSidebar />
      <main style={{
        flex: 1, minWidth: 0, display: "flex", flexDirection: "column",
        overflowY: "auto", background: T.bgCanvas,
      }}>
        <TopBar />
        <div style={{ padding: "16px 40px 40px", display: "flex", flexDirection: "column", gap: 28 }}>
          <Hero />
          <FeatureCards />
          <section style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 16 }}>
            <DraftsWidget />
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <HistoryWidget />
              <UsageWidget />
              <NoticesWidget />
            </div>
          </section>
        </div>
      </main>
    </div>
    </SidebarProvider>
  );
}
