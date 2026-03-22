import React from "react";
import {
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
} from "remotion";
import { COLORS, FONT } from "./BlueprintGrid";

type Props = {
  x: number;
  y: number;
  width: number;
  height: number;
  label: string;
  sublabel?: string;
  delay?: number;
  color?: string;
  icon?: string;
};

export const BlueprintNode: React.FC<Props> = ({
  x,
  y,
  width,
  height,
  label,
  sublabel,
  delay = 0,
  color = COLORS.cyan,
  icon,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const scale = spring({
    frame: frame - delay,
    fps,
    config: { damping: 200 },
  });

  const borderDraw = interpolate(frame - delay, [0, 25], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  if (scale <= 0.01) return null;

  const perimeter = 2 * (width + height);

  return (
    <g
      transform={`translate(${x + width / 2}, ${y + height / 2}) scale(${scale}) translate(${-(width / 2)}, ${-(height / 2)})`}
    >
      {/* Background */}
      <rect
        x={0}
        y={0}
        width={width}
        height={height}
        rx={4}
        fill="rgba(10, 22, 40, 0.8)"
        stroke={color}
        strokeWidth={2}
        strokeDasharray={`${perimeter}`}
        strokeDashoffset={perimeter * (1 - borderDraw)}
        style={{ filter: `drop-shadow(0 0 8px ${color}40)` }}
      />

      {/* Corner markers */}
      {[
        [0, 0],
        [width, 0],
        [0, height],
        [width, height],
      ].map(([cx, cy], i) => (
        <circle
          key={i}
          cx={cx}
          cy={cy}
          r={3}
          fill={color}
          opacity={borderDraw}
        />
      ))}

      {/* Icon */}
      {icon && (
        <text
          x={width / 2}
          y={height / 2 - (sublabel ? 16 : 8)}
          textAnchor="middle"
          dominantBaseline="central"
          fontSize={28}
          fill={color}
          fontFamily={FONT}
          opacity={scale}
        >
          {icon}
        </text>
      )}

      {/* Label */}
      <text
        x={width / 2}
        y={height / 2 + (icon ? 12 : sublabel ? -6 : 0)}
        textAnchor="middle"
        dominantBaseline="central"
        fontSize={18}
        fontWeight="bold"
        fill={COLORS.white}
        fontFamily={FONT}
        opacity={scale}
      >
        {label}
      </text>

      {/* Sublabel */}
      {sublabel && (
        <text
          x={width / 2}
          y={height / 2 + (icon ? 32 : 16)}
          textAnchor="middle"
          dominantBaseline="central"
          fontSize={13}
          fill={COLORS.label}
          fontFamily={FONT}
          opacity={scale}
        >
          {sublabel}
        </text>
      )}
    </g>
  );
};
