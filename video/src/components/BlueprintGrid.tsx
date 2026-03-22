import React from "react";
import { AbsoluteFill, useVideoConfig } from "remotion";

export const COLORS = {
  bg: "#0a1628",
  gridMajor: "rgba(0, 180, 255, 0.15)",
  gridMinor: "rgba(0, 180, 255, 0.06)",
  cyan: "#00b4ff",
  cyanBright: "#00e5ff",
  cyanDim: "rgba(0, 180, 255, 0.5)",
  white: "#e0f0ff",
  orange: "#ff8c00",
  green: "#00ff88",
  red: "#ff4444",
  yellow: "#ffcc00",
  text: "#c8ddf0",
  label: "rgba(0, 180, 255, 0.7)",
};

export const FONT = "'Courier New', 'Consolas', monospace";

export const BlueprintGrid: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const { width, height } = useVideoConfig();

  const minorStep = 30;
  const majorStep = 150;

  const minorLines: React.ReactNode[] = [];
  const majorLines: React.ReactNode[] = [];

  for (let x = 0; x <= width; x += minorStep) {
    const isMajor = x % majorStep === 0;
    (isMajor ? majorLines : minorLines).push(
      <line
        key={`v-${x}`}
        x1={x}
        y1={0}
        x2={x}
        y2={height}
        stroke={isMajor ? COLORS.gridMajor : COLORS.gridMinor}
        strokeWidth={isMajor ? 1 : 0.5}
      />
    );
  }

  for (let y = 0; y <= height; y += minorStep) {
    const isMajor = y % majorStep === 0;
    (isMajor ? majorLines : minorLines).push(
      <line
        key={`h-${y}`}
        x1={0}
        y1={y}
        x2={width}
        y2={y}
        stroke={isMajor ? COLORS.gridMajor : COLORS.gridMinor}
        strokeWidth={isMajor ? 1 : 0.5}
      />
    );
  }

  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.bg,
        fontFamily: FONT,
      }}
    >
      <svg
        width={width}
        height={height}
        style={{ position: "absolute", top: 0, left: 0 }}
      >
        {minorLines}
        {majorLines}
      </svg>
      {children}
    </AbsoluteFill>
  );
};
