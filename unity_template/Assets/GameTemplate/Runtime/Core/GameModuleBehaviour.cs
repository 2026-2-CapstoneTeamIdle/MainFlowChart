using UnityEngine;

namespace TeamIdle.GameTemplate.Core
{
    public abstract class GameModuleBehaviour : MonoBehaviour, IGameModule
    {
        public abstract string ModuleId { get; }

        public bool IsInitialized { get; private set; }

        protected GameContext Context { get; private set; }

        public void Initialize(GameContext context)
        {
            if (IsInitialized)
            {
                return;
            }

            Context = context;
            OnInitialize(context);
            IsInitialized = true;
        }

        public void Shutdown()
        {
            if (!IsInitialized)
            {
                return;
            }

            OnShutdown();
            Context = null;
            IsInitialized = false;
        }

        protected abstract void OnInitialize(GameContext context);

        protected virtual void OnShutdown() { }
    }
}
