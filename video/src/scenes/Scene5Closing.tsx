import React from "react";
import {
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
  Easing,
} from "remotion";
import { COLORS, FONT } from "../components/BlueprintGrid";

export const Scene5Closing: React.FC = () => {
  const frame = useCurrentFrame();
  const { width, height, fps } = useVideoConfig();

  const cx = width / 2;
  const cy = height / 2;

  // Fitness curve data points
  const curvePoints = [
    0, 2.1, 3.5, 3.0, 4.2, 5.1, 4.8, 6.0, 6.5, 7.2, 7.0, 7.8, 8.2, 8.5,
    8.7, 9.0, 9.1, 9.2, 9.3,
  ];

  const chartX = cx - 300;
  const chartY = cy - 100;
  const chartW = 600;
  const chartH = 200;

  // How many points to show based on frame
  const pointsVisible = interpolate(frame, [20, 150], [0, curvePoints.length], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Build path
  const pathPoints = curvePoints
    .slice(0, Math.ceil(pointsVisible))
    .map((val, i) => {
      const x = chartX + (i / (curvePoints.length - 1)) * chartW;
      const y = chartY + chartH - (val / 10) * chartH;
      return `${i === 0 ? "M" : "L"} ${x} ${y}`;
    })
    .join(" ");

  // Title animation
  const titleScale = spring({
    frame: frame - 170,
    fps,
    config: { damping: 15, stiffness: 200 },
  });

  // GitHub URL fade
  const urlOpacity = interpolate(frame, [200, 220], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Stable badge
  const stableBadge = spring({
    frame: frame - 155,
    fps,
    config: { damping: 200 },
  });

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
        {/* Chart axes */}
        <g
          opacity={interpolate(frame, [5, 15], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          })}
        >
          {/* Y axis */}
          <line
            x1={chartX}
            y1={chartY}
            x2={chartX}
            y2={chartY + chartH}
            stroke={COLORS.gridMajor}
            strokeWidth={1}
          />
          {/* X axis */}
          <line
            x1={chartX}
            y1={chartY + chartH}
            x2={chartX + chartW}
            y2={chartY + chartH}
            stroke={COLORS.gridMajor}
            strokeWidth={1}
          />

          {/* Y labels */}
          {[0, 2, 4, 6, 8, 10].map((v) => (
            <React.Fragment key={v}>
              <text
                x={chartX - 15}
                y={chartY + chartH - (v / 10) * chartH}
                textAnchor="end"
                dominantBaseline="central"
                fontSize={11}
                fill={COLORS.label}
                fontFamily={FONT}
              >
                {v}
              </text>
              <line
                x1={chartX}
                y1={chartY + chartH - (v / 10) * chartH}
                x2={chartX + chartW}
                y2={chartY + chartH - (v / 10) * chartH}
                stroke={COLORS.gridMinor}
                strokeWidth={0.5}
              />
            </React.Fragment>
          ))}

          {/* Axis labels */}
          <text
            x={chartX - 50}
            y={chartY + chartH / 2}
            textAnchor="middle"
            dominantBaseline="central"
            fontSize={12}
            fill={COLORS.label}
            fontFamily={FONT}
            transform={`rotate(-90, ${chartX - 50}, ${chartY + chartH / 2})`}
          >
            FITNESS
          </text>
          <text
            x={chartX + chartW / 2}
            y={chartY + chartH + 35}
            textAnchor="middle"
            fontSize={12}
            fill={COLORS.label}
            fontFamily={FONT}
          >
            GENERAZIONI
          </text>

          {/* Stability threshold line */}
          <line
            x1={chartX}
            y1={chartY + chartH - (8 / 10) * chartH}
            x2={chartX + chartW}
            y2={chartY + chartH - (8 / 10) * chartH}
            stroke={COLORS.green}
            strokeWidth={1}
            strokeDasharray="8 4"
            opacity={0.4}
          />
          <text
            x={chartX + chartW + 10}
            y={chartY + chartH - (8 / 10) * chartH}
            dominantBaseline="central"
            fontSize={10}
            fill={COLORS.green}
            fontFamily={FONT}
            opacity={0.6}
          >
            STABLE
          </text>
        </g>

        {/* Fitness curve */}
        {pointsVisible > 0 && (
          <path
            d={pathPoints}
            fill="none"
            stroke={COLORS.cyanBright}
            strokeWidth={2.5}
            style={{
              filter: `drop-shadow(0 0 6px ${COLORS.cyanBright})`,
            }}
          />
        )}

        {/* Current point glow */}
        {pointsVisible > 1 && (
          <circle
            cx={
              chartX +
              ((Math.ceil(pointsVisible) - 1) / (curvePoints.length - 1)) *
                chartW
            }
            cy={
              chartY +
              chartH -
              (curvePoints[Math.ceil(pointsVisible) - 1] / 10) * chartH
            }
            r={5}
            fill={COLORS.cyanBright}
            style={{
              filter: `drop-shadow(0 0 10px ${COLORS.cyanBright})`,
            }}
          />
        )}
      </svg>

      {/* "STABLE" badge */}
      {stableBadge > 0.01 && (
        <div
          style={{
            position: "absolute",
            top: chartY - 50,
            left: cx - 80,
            width: 160,
            textAlign: "center",
            padding: "8px 16px",
            border: `2px solid ${COLORS.green}`,
            borderRadius: 4,
            fontSize: 18,
            fontFamily: FONT,
            fontWeight: "bold",
            color: COLORS.green,
            background: "rgba(0, 255, 136, 0.05)",
            transform: `scale(${stableBadge})`,
            letterSpacing: 4,
            textShadow: `0 0 10px ${COLORS.green}`,
          }}
        >
          ◈ STABLE
        </div>
      )}

      {/* Title */}
      {titleScale > 0.01 && (
        <div
          style={{
            position: "absolute",
            bottom: 160,
            width: "100%",
            textAlign: "center",
            fontSize: 56,
            fontFamily: FONT,
            fontWeight: "bold",
            color: COLORS.cyanBright,
            letterSpacing: 3,
            textShadow: `0 0 20px ${COLORS.cyan}, 0 0 40px ${COLORS.cyan}40`,
            transform: `scale(${titleScale})`,
          }}
        >
          skill-os v2.0
        </div>
      )}

      {/* GitHub URL */}
      <div
        style={{
          position: "absolute",
          bottom: 110,
          width: "100%",
          textAlign: "center",
          fontSize: 20,
          fontFamily: FONT,
          color: COLORS.label,
          letterSpacing: 1,
          opacity: urlOpacity,
        }}
      >
        Le skill imparano dai propri errori.
      </div>

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
        ┌─ Fitness curve — Convergenza
      </div>
    </div>
  );
};
