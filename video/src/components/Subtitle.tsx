import React from "react";
import { useCurrentFrame, useVideoConfig, interpolate, Easing } from "remotion";
import { COLORS, FONT } from "./BlueprintGrid";

type SubtitleEntry = {
  text: string;
  startFrame: number;
  endFrame: number;
};

export const SUBTITLES: SubtitleEntry[] = [
  { text: "skill-os v2.0 — Server MCP auto-evolutivo", startFrame: 0, endFrame: 300 },
  { text: "Un agente AI si connette via protocollo MCP al server skill-os", startFrame: 300, endFrame: 500 },
  { text: "Il server gira in un container Docker isolato", startFrame: 500, endFrame: 600 },
  { text: "Le connessioni usano il protocollo MCP via stdio", startFrame: 600, endFrame: 900 },
  { text: "Dentro il container: quattro componenti principali", startFrame: 900, endFrame: 1100 },
  { text: "Registry: scopre e indicizza le skill disponibili", startFrame: 1100, endFrame: 1250 },
  { text: "Executor: esegue il codice in sandbox Docker isolate", startFrame: 1250, endFrame: 1400 },
  { text: "Safety: validazione, rate limiting, sistema di approvazione", startFrame: 1400, endFrame: 1550 },
  { text: "ASR Engine: il motore di auto-evoluzione", startFrame: 1550, endFrame: 1650 },
  { text: "Quando una skill fallisce, il ciclo ASR si attiva", startFrame: 1650, endFrame: 1800 },
  { text: "Diagnosi → Snapshot → Mutazione → Retry", startFrame: 1800, endFrame: 2000 },
  { text: "Se migliora: conferma. Se peggiora: rollback automatico.", startFrame: 2000, endFrame: 2250 },
  { text: "Le skill convergono verso la stabilità attraverso l'uso reale", startFrame: 2250, endFrame: 2500 },
  { text: "skill-os v2.0 — Le skill imparano dai propri errori", startFrame: 2500, endFrame: 2700 },
];

export const SubtitleBar: React.FC = () => {
  const frame = useCurrentFrame();
  const { width } = useVideoConfig();

  const current = SUBTITLES.find(
    (s) => frame >= s.startFrame && frame < s.endFrame
  );

  if (!current) return null;

  const localFrame = frame - current.startFrame;
  const duration = current.endFrame - current.startFrame;

  const fadeIn = interpolate(localFrame, [0, 10], [0, 1], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.quad),
  });

  const fadeOut = interpolate(localFrame, [duration - 10, duration], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const opacity = Math.min(fadeIn, fadeOut);

  return (
    <div
      style={{
        position: "absolute",
        bottom: 60,
        left: 0,
        width,
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        opacity,
      }}
    >
      <div
        style={{
          background: "rgba(10, 22, 40, 0.85)",
          border: `1px solid ${COLORS.cyanDim}`,
          borderRadius: 4,
          padding: "12px 32px",
          maxWidth: width * 0.8,
        }}
      >
        <span
          style={{
            fontFamily: FONT,
            fontSize: 28,
            color: COLORS.white,
            letterSpacing: 0.5,
          }}
        >
          {current.text}
        </span>
      </div>
    </div>
  );
};
