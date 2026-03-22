import React from "react";
import { AbsoluteFill, Sequence, useVideoConfig } from "remotion";
import { BlueprintGrid } from "./components/BlueprintGrid";
import { SubtitleBar } from "./components/Subtitle";
import { Scene1Intro } from "./scenes/Scene1Intro";
import { Scene2HighLevel } from "./scenes/Scene2HighLevel";
import { Scene3Container } from "./scenes/Scene3Container";
import { Scene4ASR } from "./scenes/Scene4ASR";
import { Scene5Closing } from "./scenes/Scene5Closing";

// 90 seconds at 30fps = 2700 frames
// Scene breakdown:
//   Intro:      0-300    (0-10s)
//   HighLevel:  300-900  (10-30s)
//   Container:  900-1650 (30-55s)
//   ASR:        1650-2250 (55-75s)
//   Closing:    2250-2700 (75-90s)

export const SkillOsExplainer: React.FC = () => {
  const { fps } = useVideoConfig();

  return (
    <AbsoluteFill>
      <BlueprintGrid>
        {/* Scene 1: Intro */}
        <Sequence from={0} durationInFrames={300} premountFor={fps}>
          <Scene1Intro />
        </Sequence>

        {/* Scene 2: High-level architecture */}
        <Sequence from={300} durationInFrames={600} premountFor={fps}>
          <Scene2HighLevel />
        </Sequence>

        {/* Scene 3: Inside the container */}
        <Sequence from={900} durationInFrames={750} premountFor={fps}>
          <Scene3Container />
        </Sequence>

        {/* Scene 4: ASR Engine */}
        <Sequence from={1650} durationInFrames={600} premountFor={fps}>
          <Scene4ASR />
        </Sequence>

        {/* Scene 5: Closing */}
        <Sequence from={2250} durationInFrames={450} premountFor={fps}>
          <Scene5Closing />
        </Sequence>

        {/* Subtitles overlay - always on top */}
        <Sequence from={0} durationInFrames={2700} premountFor={fps}>
          <SubtitleBar />
        </Sequence>
      </BlueprintGrid>
    </AbsoluteFill>
  );
};
