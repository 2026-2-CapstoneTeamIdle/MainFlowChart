using System.Collections.Generic;
using UnityEngine;

namespace TeamIdle.GameTemplate.Core
{
    [CreateAssetMenu(fileName = "GameTemplateConfig", menuName = "Team IDLE/Game Template Config")]
    public sealed class GameTemplateConfig : ScriptableObject
    {
        [SerializeField]
        private string contractVersion = "3.1.0";

        [SerializeField]
        private string gameTitle = "Generated 2D Game";

        [SerializeField]
        private string genre = "Unassigned";

        [SerializeField]
        private string viewpoint = "Unassigned";

        [SerializeField]
        private string entryScene = "Assets/Scenes/Bootstrap.unity";

        [SerializeField]
        private List<string> selectedModules = new();

        public string ContractVersion => contractVersion;

        public string GameTitle => gameTitle;

        public string Genre => genre;

        public string Viewpoint => viewpoint;

        public string EntryScene => entryScene;

        public IReadOnlyList<string> SelectedModules => selectedModules;

        public void Configure(
            string nextContractVersion,
            string nextGameTitle,
            string nextGenre,
            string nextViewpoint,
            string nextEntryScene,
            IEnumerable<string> nextSelectedModules
        )
        {
            contractVersion = nextContractVersion;
            gameTitle = nextGameTitle;
            genre = nextGenre;
            viewpoint = nextViewpoint;
            entryScene = nextEntryScene;
            selectedModules = new List<string>(nextSelectedModules);
        }

        public bool IsValid(out string issue)
        {
            if (string.IsNullOrWhiteSpace(contractVersion))
            {
                issue = "Contract version is required.";
                return false;
            }

            if (string.IsNullOrWhiteSpace(gameTitle))
            {
                issue = "Game title is required.";
                return false;
            }

            if (string.IsNullOrWhiteSpace(entryScene))
            {
                issue = "Entry scene is required.";
                return false;
            }

            if (string.IsNullOrWhiteSpace(viewpoint))
            {
                issue = "Viewpoint is required.";
                return false;
            }

            issue = string.Empty;
            return true;
        }
    }
}
