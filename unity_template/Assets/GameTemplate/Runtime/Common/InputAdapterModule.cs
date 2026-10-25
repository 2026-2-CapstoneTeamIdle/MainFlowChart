using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.Common
{
    public sealed class InputAdapterModule : GameModuleBehaviour
    {
        public override string ModuleId => "input_adapter";
#if UNITY_EDITOR
        public static bool TestInputEnabled;
        public static Vector2 TestMovement;
        public static bool TestDashPressed;
        public static bool TestConfirmPressed;
#endif
        public Vector2 Movement =>
#if UNITY_EDITOR
            TestInputEnabled
                ? TestMovement
                :
#endif
                new(Input.GetAxisRaw("Horizontal"), Input.GetAxisRaw("Vertical"));
        public bool ConfirmPressed =>
#if UNITY_EDITOR
            TestInputEnabled
                ? TestConfirmPressed
                :
#endif
                Input.GetButtonDown("Submit") || Input.GetKeyDown(KeyCode.Space);
        public bool CancelPressed =>
            Input.GetButtonDown("Cancel") || Input.GetKeyDown(KeyCode.Escape);
        public bool DashPressed =>
#if UNITY_EDITOR
            TestInputEnabled
                ? TestDashPressed
                :
#endif
                Input.GetKeyDown(KeyCode.LeftShift) || Input.GetKeyDown(KeyCode.RightShift);

        protected override void OnInitialize(GameContext context) => context.Register(this);
    }
}
