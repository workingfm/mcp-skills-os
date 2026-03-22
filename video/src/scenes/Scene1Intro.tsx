import React from "react";
import {
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
  Easing,
} from "remotion";
import { COLORS, FONT } from "../components/BlueprintGrid";

export const Scene1Intro: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Title typewriter effect
  const title = "skill-os v2.0";
  const charsVisible = Math.floor(
    interpolate(frame, [15, 15 + title.length * 3], [0, title.length], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    })
  );
  const visibleTitle = title.slice(0, charsVisible);
  const showCursor = frame % 16 < 10 && frame < 15 + title.length * 3 + 30;

  // Subtitle fade in
  const subtitleOpacity = interpolate(frame, [100, 120], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.quad),
  });

  // Horizontal scan line
  const scanY = interpolate(frame, [0, 60], [-10, 1090], {
    extrapolateRight: "clamp",
  });

  // Corner bracket decorations
  const bracketScale = spring({
    frame: frame - 5,
    fps,
    config: { damping: 200 },
  });

  // Version badge
  const badgeScale = spring({
    frame: frame - 130,
    fps,
    config: { damping: 15, stiffness: 200 },
  });

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        alignItems: "center",
        position: "relative",
      }}
    >
      {/* Scan line */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: scanY,
          height: 2,
          background: `linear-gradient(90deg, transparent, ${COLORS.cyan}, transparent)`,
          opacity: 0.6,
          filter: `drop-shadow(0 0 8px ${COLORS.cyan})`,
        }}
      />

      {/* Corner brackets */}
      <svg
        width={600}
        height={200}
        style={{
          position: "absolute",
          transform: `scale(${bracketScale})`,
        }}
      >
        {/* Top-left */}
        <path
          d="M 20 60 L 20 20 L 60 20"
          stroke={COLORS.cyan}
          strokeWidth={2}
          fill="none"
        />
        {/* Top-right */}
        <path
          d="M 540 20 L 580 20 L 580 60"
          stroke={COLORS.cyan}
          strokeWidth={2}
          fill="none"
        />
        {/* Bottom-left */}
        <path
          d="M 20 140 L 20 180 L 60 180"
          stroke={COLORS.cyan}
          strokeWidth={2}
          fill="none"
        />
        {/* Bottom-right */}
        <path
          d="M 540 180 L 580 180 L 580 140"
          stroke={COLORS.cyan}
          strokeWidth={2}
          fill="none"
        />
      </svg>

      {/* Title */}
      <div
        style={{
          fontSize: 72,
          fontFamily: FONT,
          color: COLORS.cyanBright,
          fontWeight: "bold",
          letterSpacing: 4,
          textShadow: `0 0 20px ${COLORS.cyan}, 0 0 40px ${COLORS.cyan}40`,
          position: "relative",
        }}
      >
        {visibleTitle}
        {showCursor && (
          <span style={{ color: COLORS.cyan, opacity: 0.8 }}>▌</span>
        )}
      </div>

      {/* Subtitle */}
      <div
        style={{
          fontSize: 24,
          fontFamily: FONT,
          color: COLORS.label,
          marginTop: 20,
          letterSpacing: 2,
          opacity: subtitleOpacity,
          textTransform: "uppercase",
        }}
      >
        MCP Server auto-evolutivo
      </div>

      {/* Version badge */}
      <div
        style={{
          marginTop: 30,
          padding: "6px 20px",
          border: `1px solid ${COLORS.green}`,
          borderRadius: 3,
          fontSize: 14,
          fontFamily: FONT,
          color: COLORS.green,
          letterSpacing: 1,
          transform: `scale(${badgeScale})`,
          opacity: badgeScale,
        }}
      >
        ADAPTIVE SKILL REINFORCEMENT
      </div>
    </div>
  );
};
