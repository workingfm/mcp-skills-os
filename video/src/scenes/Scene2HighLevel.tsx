import React from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS } from "../components/BlueprintGrid";
import { BlueprintNode } from "../components/BlueprintNode";
import { AnimatedLine } from "../components/AnimatedLine";

export const Scene2HighLevel: React.FC = () => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();

  const cx = width / 2;
  const cy = height / 2 - 40;

  // Node positions
  const nodeW = 260;
  const nodeH = 90;
  const spacing = 340;

  const nodes = [
    {
      x: cx - spacing - nodeW / 2,
      y: cy - nodeH / 2,
      label: "Claude Code",
      sublabel: "AI Agent (Client)",
      icon: "⬡",
      delay: 10,
      color: COLORS.cyanBright,
    },
    {
      x: cx - nodeW / 2,
      y: cy - nodeH / 2,
      label: "MCP Protocol",
      sublabel: "stdio transport",
      icon: "⇋",
      delay: 30,
      color: COLORS.yellow,
    },
    {
      x: cx + spacing - nodeW / 2,
      y: cy - nodeH / 2,
      label: "skill-os",
      sublabel: "Docker Container",
      icon: "◈",
      delay: 50,
      color: COLORS.green,
    },
  ];

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        position: "relative",
      }}
    >
      <svg
        width={width}
        height={height}
        style={{ position: "absolute", top: 0, left: 0 }}
      >
        {/* Connection lines */}
        <AnimatedLine
          x1={nodes[0].x + nodeW}
          y1={cy}
          x2={nodes[1].x}
          y2={cy}
          delay={40}
          duration={20}
          color={COLORS.cyan}
        />
        <AnimatedLine
          x1={nodes[1].x + nodeW}
          y1={cy}
          x2={nodes[2].x}
          y2={cy}
          delay={60}
          duration={20}
          color={COLORS.cyan}
        />

        {/* Nodes */}
        {nodes.map((n, i) => (
          <BlueprintNode
            key={i}
            x={n.x}
            y={n.y}
            width={nodeW}
            height={nodeH}
            label={n.label}
            sublabel={n.sublabel}
            icon={n.icon}
            delay={n.delay}
            color={n.color}
          />
        ))}

        {/* Labels below */}
        <text
          x={nodes[0].x + nodeW / 2}
          y={cy + nodeH / 2 + 35}
          textAnchor="middle"
          fontSize={13}
          fill={COLORS.label}
          fontFamily="'Courier New', monospace"
          opacity={frame > 25 ? 1 : 0}
        >
          list_skills() | execute() | create_skill()
        </text>

        <text
          x={nodes[1].x + nodeW / 2}
          y={cy + nodeH / 2 + 35}
          textAnchor="middle"
          fontSize={13}
          fill={COLORS.label}
          fontFamily="'Courier New', monospace"
          opacity={frame > 45 ? 1 : 0}
        >
          JSON-RPC 2.0
        </text>

        <text
          x={nodes[2].x + nodeW / 2}
          y={cy + nodeH / 2 + 35}
          textAnchor="middle"
          fontSize={13}
          fill={COLORS.label}
          fontFamily="'Courier New', monospace"
          opacity={frame > 65 ? 1 : 0}
        >
          FastMCP Server
        </text>

        {/* Data flow particles */}
        {frame > 80 && (
          <>
            {[0, 1, 2].map((i) => {
              const t =
                ((frame - 80 + i * 30) % 90) / 90;
              const px =
                nodes[0].x + nodeW + t * (nodes[2].x - nodes[0].x - nodeW);
              return (
                <circle
                  key={`p-${i}`}
                  cx={px}
                  cy={cy}
                  r={3}
                  fill={COLORS.cyanBright}
                  style={{
                    filter: `drop-shadow(0 0 6px ${COLORS.cyanBright})`,
                  }}
                  opacity={0.8}
                />
              );
            })}
          </>
        )}
      </svg>

      {/* Section label */}
      <div
        style={{
          position: "absolute",
          top: 40,
          left: 60,
          fontSize: 14,
          fontFamily: "'Courier New', monospace",
          color: COLORS.label,
          textTransform: "uppercase",
          letterSpacing: 3,
          opacity: frame > 5 ? 1 : 0,
        }}
      >
        ┌─ Architettura ad alto livello
      </div>
    </div>
  );
};
