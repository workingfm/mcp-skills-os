import React from "react";
import {
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
  Easing,
} from "remotion";
import { COLORS, FONT } from "../components/BlueprintGrid";

type FlowStep = {
  label: string;
  color: string;
  x: number;
  y: number;
};

export const Scene4ASR: React.FC = () => {
  const frame = useCurrentFrame();
  const { width, height, fps } = useVideoConfig();

  const cx = width / 2;

  // Flow steps in a circular/flowchart layout
  const steps: FlowStep[] = [
    { label: "EXECUTE", color: COLORS.cyan, x: cx, y: 160 },
    { label: "FAIL", color: COLORS.red, x: cx + 300, y: 250 },
    { label: "DIAGNOSE", color: COLORS.yellow, x: cx + 300, y: 400 },
    { label: "SNAPSHOT", color: COLORS.cyanBright, x: cx, y: 490 },
    { label: "MUTATE", color: COLORS.orange, x: cx - 300, y: 400 },
    { label: "RETRY", color: COLORS.green, x: cx - 300, y: 250 },
  ];

  const stepW = 160;
  const stepH = 56;
  const stepDelay = 20;

  // Outcome branch
  const showOutcome = frame > steps.length * stepDelay + 30;

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
        {/* Flow steps */}
        {steps.map((step, i) => {
          const delay = i * stepDelay + 10;
          const s = spring({
            frame: frame - delay,
            fps,
            config: { damping: 200 },
          });

          if (s <= 0.01) return null;

          const borderProgress = interpolate(
            frame - delay,
            [0, 20],
            [0, 1],
            {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }
          );

          return (
            <g key={i}>
              {/* Step box */}
              <rect
                x={step.x - stepW / 2}
                y={step.y - stepH / 2}
                width={stepW}
                height={stepH}
                rx={4}
                fill="rgba(10, 22, 40, 0.85)"
                stroke={step.color}
                strokeWidth={2}
                opacity={s}
                style={{
                  filter: `drop-shadow(0 0 8px ${step.color}50)`,
                }}
              />

              {/* Step number circle */}
              <circle
                cx={step.x - stepW / 2 + 20}
                cy={step.y}
                r={12}
                fill={step.color}
                opacity={s * 0.3}
              />
              <text
                x={step.x - stepW / 2 + 20}
                y={step.y}
                textAnchor="middle"
                dominantBaseline="central"
                fontSize={12}
                fontWeight="bold"
                fill={COLORS.white}
                fontFamily={FONT}
                opacity={s}
              >
                {i + 1}
              </text>

              {/* Step label */}
              <text
                x={step.x + 10}
                y={step.y}
                textAnchor="middle"
                dominantBaseline="central"
                fontSize={16}
                fontWeight="bold"
                fill={COLORS.white}
                fontFamily={FONT}
                opacity={s}
              >
                {step.label}
              </text>

              {/* Connection to next step */}
              {i < steps.length - 1 && (
                <ConnectionLine
                  from={step}
                  to={steps[i + 1]}
                  stepW={stepW}
                  stepH={stepH}
                  frame={frame}
                  delay={delay + 15}
                  color={step.color}
                />
              )}
            </g>
          );
        })}

        {/* Connection from RETRY back to EXECUTE */}
        {frame > steps.length * stepDelay + 10 && (
          <ConnectionLine
            from={steps[5]}
            to={steps[0]}
            stepW={stepW}
            stepH={stepH}
            frame={frame}
            delay={steps.length * stepDelay + 10}
            color={COLORS.green}
          />
        )}

        {/* Outcome branches */}
        {showOutcome && (
          <>
            {/* CONFIRM branch */}
            <g
              opacity={interpolate(
                frame,
                [steps.length * stepDelay + 30, steps.length * stepDelay + 50],
                [0, 1],
                { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
              )}
            >
              <rect
                x={cx + 120}
                y={600}
                width={180}
                height={50}
                rx={4}
                fill="rgba(0, 255, 136, 0.1)"
                stroke={COLORS.green}
                strokeWidth={2}
              />
              <text
                x={cx + 210}
                y={625}
                textAnchor="middle"
                dominantBaseline="central"
                fontSize={16}
                fontWeight="bold"
                fill={COLORS.green}
                fontFamily={FONT}
              >
                ✓ CONFIRM
              </text>

              {/* Arrow down from cycle */}
              <line
                x1={cx + 60}
                y1={steps[3].y + stepH / 2}
                x2={cx + 210}
                y2={600}
                stroke={COLORS.green}
                strokeWidth={1.5}
                strokeDasharray="6 3"
              />
            </g>

            {/* ROLLBACK branch */}
            <g
              opacity={interpolate(
                frame,
                [steps.length * stepDelay + 40, steps.length * stepDelay + 60],
                [0, 1],
                { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
              )}
            >
              <rect
                x={cx - 300}
                y={600}
                width={180}
                height={50}
                rx={4}
                fill="rgba(255, 68, 68, 0.1)"
                stroke={COLORS.red}
                strokeWidth={2}
              />
              <text
                x={cx - 210}
                y={625}
                textAnchor="middle"
                dominantBaseline="central"
                fontSize={16}
                fontWeight="bold"
                fill={COLORS.red}
                fontFamily={FONT}
              >
                ✗ ROLLBACK
              </text>

              <line
                x1={cx - 60}
                y1={steps[3].y + stepH / 2}
                x2={cx - 210}
                y2={600}
                stroke={COLORS.red}
                strokeWidth={1.5}
                strokeDasharray="6 3"
              />
            </g>
          </>
        )}

        {/* RL mapping legend */}
        {frame > 160 && (
          <g
            opacity={interpolate(frame, [160, 180], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            })}
          >
            <text
              x={80}
              y={height - 120}
              fontSize={12}
              fill={COLORS.label}
              fontFamily={FONT}
            >
              {"Reward: +1.0 success │ -0.5 error │ -1.0 crash"}
            </text>
            <text
              x={80}
              y={height - 95}
              fontSize={12}
              fill={COLORS.label}
              fontFamily={FONT}
            >
              {"Policy: failure-driven diagnosis → targeted mutation"}
            </text>
            <text
              x={80}
              y={height - 70}
              fontSize={12}
              fill={COLORS.label}
              fontFamily={FONT}
            >
              {"Convergence: 10 successi consecutivi → status 'stable'"}
            </text>
          </g>
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
          color: COLORS.orange,
          textTransform: "uppercase",
          letterSpacing: 3,
          opacity: frame > 5 ? 1 : 0,
        }}
      >
        ┌─ ASR Engine — Ciclo di evoluzione
      </div>
    </div>
  );
};

// Helper component for connection lines
const ConnectionLine: React.FC<{
  from: FlowStep;
  to: FlowStep;
  stepW: number;
  stepH: number;
  frame: number;
  delay: number;
  color: string;
}> = ({ from, to, stepW, stepH, frame, delay, color }) => {
  const progress = interpolate(frame - delay, [0, 15], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.quad),
  });

  if (progress <= 0) return null;

  // Determine connection points
  const dx = to.x - from.x;
  const dy = to.y - from.y;

  let x1: number, y1: number, x2: number, y2: number;

  if (Math.abs(dx) > Math.abs(dy)) {
    // Horizontal dominant
    x1 = from.x + (dx > 0 ? stepW / 2 : -stepW / 2);
    y1 = from.y;
    x2 = to.x + (dx > 0 ? -stepW / 2 : stepW / 2);
    y2 = to.y;
  } else {
    // Vertical dominant
    x1 = from.x;
    y1 = from.y + (dy > 0 ? stepH / 2 : -stepH / 2);
    x2 = to.x;
    y2 = to.y + (dy > 0 ? -stepH / 2 : stepH / 2);
  }

  const cx1 = x1 + (x2 - x1) * progress;
  const cy1 = y1 + (y2 - y1) * progress;

  const angle = Math.atan2(y2 - y1, x2 - x1);

  return (
    <g>
      <line
        x1={x1}
        y1={y1}
        x2={cx1}
        y2={cy1}
        stroke={color}
        strokeWidth={1.5}
        opacity={0.6}
        style={{ filter: `drop-shadow(0 0 3px ${color})` }}
      />
      {progress > 0.9 && (
        <polygon
          points={`
            ${x2},${y2}
            ${x2 - 8 * Math.cos(angle - 0.4)},${y2 - 8 * Math.sin(angle - 0.4)}
            ${x2 - 8 * Math.cos(angle + 0.4)},${y2 - 8 * Math.sin(angle + 0.4)}
          `}
          fill={color}
          opacity={0.8}
        />
      )}
    </g>
  );
};
