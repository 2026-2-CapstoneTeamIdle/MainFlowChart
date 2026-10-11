namespace TeamIdle.GameTemplate.Core
{
    public interface IGameModule
    {
        string ModuleId { get; }

        void Initialize(GameContext context);

        void Shutdown();
    }
}
