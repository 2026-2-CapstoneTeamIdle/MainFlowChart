namespace TeamIdle.GameTemplate.Core
{
    public sealed class GameContext
    {
        public GameContext(GameTemplateConfig config, ValidationProbe validation)
        {
            Config = config;
            Validation = validation;
        }

        public GameTemplateConfig Config { get; }

        public ValidationProbe Validation { get; }
    }
}
