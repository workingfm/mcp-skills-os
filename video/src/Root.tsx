import { Composition } from "remotion";
import { SkillOsExplainer } from "./SkillOsExplainer";

export const RemotionRoot = () => {
  return (
    <Composition
      id="SkillOsExplainer"
      component={SkillOsExplainer}
      durationInFrames={2700}
      fps={30}
      width={1920}
      height={1080}
    />
  );
};
