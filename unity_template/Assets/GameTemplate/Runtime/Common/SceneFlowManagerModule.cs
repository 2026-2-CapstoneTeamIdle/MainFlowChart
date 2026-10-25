using System;
using System.Collections;
using TeamIdle.GameTemplate.Core;
using UnityEngine.SceneManagement;

namespace TeamIdle.GameTemplate.Common
{
    public sealed class SceneFlowManagerModule : GameModuleBehaviour
    {
        private bool isLoading;
        public override string ModuleId => "scene_flow_manager";
        public bool IsLoading => isLoading;
        public event Action<string> SceneLoaded;

        public void Load(string sceneName)
        {
            if (!isLoading && !string.IsNullOrWhiteSpace(sceneName))
                StartCoroutine(LoadRoutine(sceneName));
        }

        public void ReloadCurrent() => Load(SceneManager.GetActiveScene().name);

        protected override void OnInitialize(GameContext context) => context.Register(this);

        private IEnumerator LoadRoutine(string sceneName)
        {
            isLoading = true;
            var operation = SceneManager.LoadSceneAsync(sceneName);
            if (operation == null)
            {
                isLoading = false;
                yield break;
            }
            yield return operation;
            isLoading = false;
            SceneLoaded?.Invoke(sceneName);
        }
    }
}
