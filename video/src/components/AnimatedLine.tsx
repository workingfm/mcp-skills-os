import React from "react";
import { useCurrentFrame, useVideoConfig, interpolate, Easing } from "remotion";
import { COLORS } from "./BlueprintGrid";

type Props = {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  delay?: number;
  duration?: number;
  color?: string;
  strokeWidth?: number;
  dashed?: boolean;
  arrow?: boolean;
};

export const AnimatedLine: React.FC<Props> = ({
  x1,
  y1,
  x2,
  y2,
  delay = 0,
  duration = 20,
  color = COLORS.cyan,
  strokeWidth = 2,
  dashed = false,
  arrow = true,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const progress = interpolate(frame - delay, [0, duration], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.quad),
  });

  if (progress <= 0) return null;

  const cx = x1 + (x2 - x1) * progress;
  const cy = y1 + (y2 - y1) * progress;

  const angle = Math.atan2(y2 - y1, x2 - x1);
  const arrowSize = 10;

  return (
    <g>
      <line
        x1={x1}
        y1={y1}
        x2={cx}
        y2={cy}
        stroke={color}
        strokeWidth={strokeWidth}
        strokeDasharray={dashed ? "8 4" : undefined}
        style={{ filter: `drop-shadow(0 0 4px ${color})` }}
      />
      {arrow && progress > 0.9 && (
        <polygon
          points={`
            ${x2},${y2}
            ${x2 - arrowSize * Math.cos(angle - 0.4)},${y2 - arrowSize * Math.sin(angle - 0.4)}
            ${x2 - arrowSize * Math.cos(angle + 0.4)},${y2 - arrowSize * Math.sin(angle + 0.4)}
          `}
          fill={color}
          opacity={interpolate(progress, [0.9, 1], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          })}
        />
      )}
    </g>
  );
};
