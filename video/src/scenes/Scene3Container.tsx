import React from "react";
import {
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
  Easing,
} from "remotion";
import { COLORS, FONT } from "../components/BlueprintGrid";
import { BlueprintNode } from "../components/BlueprintNode";
import { AnimatedLine } from "../components/AnimatedLine";

export const Scene3Container: React.FC = () => {
  const frame = useCurrentFrame();
  const { width, height, fps } = useVideoConfig();

  const cx = width / 2;
  const cy = height / 2;

  // Container border animation
  const containerScale = spring({
    frame,
    fps,
    config: { damping: 200 },
  });

  const containerW = 900;
  const containerH = 500;
  const containerX = cx - containerW / 2;
  const containerY = cy - containerH / 2 + 20;

  // Module positions inside container
  const modW = 180;
  const modH = 100;
  const modGap = 30;
  const modY1 = containerY + 80;
  const modY2 = containerY + 80 + modH + modGap + 40;

  const modules = [
    {
      x: containerX + 60,
      y: modY1,
      label: "Registry",
      sublabel: "Hot-reload",
      color: COLORS.cyanBright,
      delay: 30,
    },
    {
      x: containerX + 60 + modW + modGap,
      y: modY1,
      label: "Executor",
      sublabel: "Docker sandbox",
      color: COLORS.green,
      delay: 45,
    },
    {
      x: containerX + 60 + (modW + modGap) * 2,
      y: modY1,
      label: "Safety",
      sublabel: "Rate limit + Approval",
      color: COLORS.yellow,
      delay: 60,
    },
    {
      x: cx - modW / 2,
      y: modY2,
      label: "ASR Engine",
      sublabel: "Adaptive Skill RL",
      color: COLORS.orange,
      delay: 80,
    },
  ];

  const containerBorderProgress = interpolate(frame, [0, 30], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.quad),
  });

  const containerPerimeter = 2 * (containerW + containerH);

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
        {/* Container outline */}
        <rect
          x={containerX}
          y={containerY}
          width={containerW}
          height={containerH}
          rx={6}
          fill="rgba(10, 22, 40, 0.5)"
          stroke={COLORS.cyan}
          strokeWidth={2}
          strokeDasharray={`${containerPerimeter}`}
          strokeDashoffset={containerPerimeter * (1 - containerBorderProgress)}
          style={{ filter: `drop-shadow(0 0 12px ${COLORS.cyan}30)` }}
        />

        {/* Container label */}
        <text
          x={containerX + 20}
          y={containerY + 30}
          fontSize={16}
          fill={COLORS.cyan}
          fontFamily={FONT}
          fontWeight="bold"
          opacity={containerBorderProgress}
        >
          {"◈ skill-os Container"}
        </text>

        {/* Separator line */}
        <line
          x1={containerX + 20}
          y1={containerY + 50}
          x2={containerX + containerW - 20}
          y2={containerY + 50}
          stroke={COLORS.gridMajor}
          strokeWidth={1}
          opacity={containerBorderProgress}
        />

        {/* Internal modules */}
        {modules.map((m, i) => (
          <BlueprintNode
            key={i}
            x={m.x}
            y={m.y}
            width={modW}
            height={modH}
            label={m.label}
            sublabel={m.sublabel}
            delay={m.delay}
            color={m.color}
          />
        ))}

        {/* Connection: Registry → Executor */}
        <AnimatedLine
          x1={modules[0].x + modW}
          y1={modY1 + modH / 2}
          x2={modules[1].x}
          y2={modY1 + modH / 2}
          delay={55}
          duration={15}
          color={COLORS.cyanDim}
        />

        {/* Connection: Executor → Safety */}
        <AnimatedLine
          x1={modules[1].x + modW}
          y1={modY1 + modH / 2}
          x2={modules[2].x}
          y2={modY1 + modH / 2}
          delay={70}
          duration={15}
          color={COLORS.cyanDim}
        />

        {/* Connection: Executor → ASR */}
        <AnimatedLine
          x1={modules[1].x + modW / 2}
          y1={modY1 + modH}
          x2={modules[3].x + modW / 2}
          y2={modY2}
          delay={90}
          duration={20}
          color={COLORS.orange}
          dashed
        />

        {/* Feedback loop arrow from ASR back to Registry */}
        {frame > 110 && (
          <AnimatedLine
            x1={modules[3].x}
            y1={modY2 + modH / 2}
            x2={modules[0].x + modW / 2}
            y2={modY1 + modH}
            delay={110}
            duration={20}
            color={COLORS.orange}
            dashed
          />
        )}

        {/* Data flow label */}
        {frame > 120 && (
          <text
            x={cx}
            y={modY2 + modH + 50}
            textAnchor="middle"
            fontSize={14}
            fill={COLORS.label}
            fontFamily={FONT}
            opacity={interpolate(frame, [120, 140], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            })}
          >
            {"execute() → sandbox → reward → evolve → retry"}
          </text>
        )}
      </svg>

      {/* Section label */}
      <div
        style={{
          position: "absolute",
          top: 40,
          left: 60,
          fontSize: 14,
          fontFamily: FONT,
          color: COLORS.label,
          textTransform: "uppercase",
          letterSpacing: 3,
          opacity: frame > 5 ? 1 : 0,
        }}
      >
        ┌─ Dentro il container
      </div>
    </div>
  );
};
