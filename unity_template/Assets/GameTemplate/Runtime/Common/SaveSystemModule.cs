using System;
using System.Collections.Generic;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.Common
{
    public sealed class SaveSystemModule : GameModuleBehaviour
    {
        [Serializable]
        private sealed class SaveData
        {
            public List<GameStateStoreModule.Entry> entries = new();
        }

        [SerializeField]
        private string playerPrefsKey = "team_idle_game_save";
        private GameStateStoreModule stateStore;
        public override string ModuleId => "save_system";
        public bool HasSave => PlayerPrefs.HasKey(playerPrefsKey);
        public event Action Saved;
        public event Action Loaded;

        public void Save()
        {
            var data = new SaveData
            {
                entries = new List<GameStateStoreModule.Entry>(stateStore.CreateSnapshot()),
            };
            PlayerPrefs.SetString(playerPrefsKey, JsonUtility.ToJson(data));
            PlayerPrefs.Save();
            Saved?.Invoke();
        }

        public bool Load()
        {
            if (!PlayerPrefs.HasKey(playerPrefsKey))
                return false;
            var data = JsonUtility.FromJson<SaveData>(PlayerPrefs.GetString(playerPrefsKey));
            stateStore.Restore(data?.entries ?? new List<GameStateStoreModule.Entry>());
            Loaded?.Invoke();
            return true;
        }

        public void DeleteSave() => PlayerPrefs.DeleteKey(playerPrefsKey);

        protected override void OnInitialize(GameContext context)
        {
            stateStore = context.GetRequired<GameStateStoreModule>();
            context.Register(this);
        }
    }
}
