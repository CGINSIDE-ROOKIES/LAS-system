import { useEffect, useRef } from "react";
import { Network } from "lucide-react";

const nodes = [
  { id: "labor", label: "근로기준법", x: 200, y: 80, primary: true },
  { id: "a17", label: "제17조", x: 80, y: 180, primary: false },
  { id: "a50", label: "제50조", x: 200, y: 200, primary: false },
  { id: "a56", label: "제56조", x: 320, y: 180, primary: false },
  { id: "a114", label: "제114조", x: 140, y: 280, primary: false },
  { id: "subcontract", label: "하도급법", x: 400, y: 100, primary: true },
  { id: "s3", label: "제3조", x: 380, y: 260, primary: false },
  { id: "s13", label: "제13조", x: 480, y: 220, primary: false },
];

const edges = [
  { from: "labor", to: "a17" },
  { from: "labor", to: "a50" },
  { from: "labor", to: "a56" },
  { from: "a17", to: "a114" },
  { from: "subcontract", to: "s3" },
  { from: "subcontract", to: "s13" },
  { from: "a56", to: "a50" },
];

export function LawGraphPanel() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = rect.height;
    const scaleX = w / 560;
    const scaleY = h / 340;

    ctx.clearRect(0, 0, w, h);

    // Draw edges
    ctx.strokeStyle = "hsl(220, 16%, 80%)";
    ctx.lineWidth = 1;
    edges.forEach((e) => {
      const from = nodes.find((n) => n.id === e.from)!;
      const to = nodes.find((n) => n.id === e.to)!;
      ctx.beginPath();
      ctx.moveTo(from.x * scaleX, from.y * scaleY);
      ctx.lineTo(to.x * scaleX, to.y * scaleY);
      ctx.stroke();
    });

    // Draw nodes
    nodes.forEach((node) => {
      const x = node.x * scaleX;
      const y = node.y * scaleY;
      const r = node.primary ? 28 : 20;

      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = node.primary ? "hsl(217, 91%, 50%)" : "hsl(217, 91%, 95%)";
      ctx.fill();
      ctx.strokeStyle = node.primary ? "hsl(217, 91%, 40%)" : "hsl(217, 60%, 75%)";
      ctx.lineWidth = 1.5;
      ctx.stroke();

      ctx.fillStyle = node.primary ? "#fff" : "hsl(220, 30%, 20%)";
      ctx.font = `${node.primary ? 11 : 10}px system-ui, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(node.label, x, y);
    });
  }, []);

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <Network className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-semibold text-foreground">법령 관계 그래프</h2>
        </div>
      </div>
      <div className="flex-1 p-4">
        <canvas ref={canvasRef} className="h-full w-full rounded-lg border border-border bg-card" />
      </div>
    </div>
  );
}
