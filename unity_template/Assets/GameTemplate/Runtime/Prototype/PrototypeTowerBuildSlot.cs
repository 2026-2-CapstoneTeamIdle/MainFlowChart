using UnityEngine;

namespace TeamIdle.GameTemplate.Prototype
{
    public sealed class PrototypeTowerBuildSlot : MonoBehaviour
    {
        private PrototypeTowerBuildController controller;
        public bool IsOccupied { get; private set; }

        public void Bind(PrototypeTowerBuildController owner)
        {
            controller = owner;
        }

        public void MarkBuilt()
        {
            MarkBuilt(new Color(0.25f, 0.8f, 1f));
        }

        public void MarkBuilt(Color towerColor)
        {
            IsOccupied = true;
            transform.localScale = new Vector3(1.1f, 1.4f, 1f);
            if (TryGetComponent<SpriteRenderer>(out var renderer))
            {
                renderer.color = towerColor;
            }
        }

        public bool Activate()
        {
            return controller != null && controller.TryBuild(this);
        }

        private void OnMouseDown()
        {
            Activate();
        }
    }
}
