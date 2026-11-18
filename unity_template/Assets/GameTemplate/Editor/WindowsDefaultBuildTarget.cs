using UnityEditor;
using UnityEngine;

namespace TeamIdle.GameTemplate.Editor
{
    internal static class WindowsDefaultBuildTarget
    {
        private const string SessionKey = "TeamIdle.WindowsBuildTargetDefaultChecked";

        [InitializeOnLoadMethod]
        private static void ScheduleDefaultSelection()
        {
            // Docker validation and WebGL preview run in batch mode on Linux.
            if (Application.platform != RuntimePlatform.WindowsEditor || Application.isBatchMode)
            {
                return;
            }

            EditorApplication.delayCall += SelectWindowsForEditorSession;
        }

        private static void SelectWindowsForEditorSession()
        {
            // A manual platform change in this Editor session should remain the user's choice.
            if (SessionState.GetBool(SessionKey, false))
            {
                return;
            }

            SessionState.SetBool(SessionKey, true);
            if (EditorUserBuildSettings.activeBuildTarget == BuildTarget.StandaloneWindows64)
            {
                return;
            }

            if (
                !EditorUserBuildSettings.SwitchActiveBuildTargetAsync(
                    BuildTargetGroup.Standalone,
                    BuildTarget.StandaloneWindows64
                )
            )
            {
                Debug.LogWarning("Could not select Windows 64-bit build target on Editor startup.");
            }
        }
    }
}
