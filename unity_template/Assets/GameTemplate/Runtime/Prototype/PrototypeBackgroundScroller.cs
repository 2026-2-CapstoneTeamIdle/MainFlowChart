using UnityEngine;

namespace TeamIdle.GameTemplate.Prototype
{
    /// <summary>
    /// Keeps a generated background image covering the camera view wherever the camera goes.
    /// The sprite is scaled so one tile covers the view height and repeated with
    /// <see cref="SpriteDrawMode.Tiled"/>. <c>parallax</c> sets how fast the image scrolls:
    /// 0 keeps it fixed to the camera, 1 keeps it fixed to the world.
    /// </summary>
    [RequireComponent(typeof(SpriteRenderer))]
    public sealed class PrototypeBackgroundScroller : MonoBehaviour
    {
        [SerializeField]
        private float parallax = 0.25f;

        [SerializeField]
        private bool tileVertically;

        [SerializeField]
        private float overscan = 1.1f;

        private SpriteRenderer spriteRenderer;
        private Camera targetCamera;

        public float Parallax => parallax;

        public bool TileVertically => tileVertically;

        public void Configure(float nextParallax, bool nextTileVertically)
        {
            parallax = Mathf.Clamp01(nextParallax);
            tileVertically = nextTileVertically;
            Apply();
        }

        private void LateUpdate()
        {
            Apply();
        }

        public void Apply()
        {
            if (spriteRenderer == null)
            {
                spriteRenderer = GetComponent<SpriteRenderer>();
            }
            if (targetCamera == null)
            {
                targetCamera = Camera.main;
            }

            var sprite = spriteRenderer == null ? null : spriteRenderer.sprite;
            if (targetCamera == null || !targetCamera.orthographic || sprite == null)
            {
                return;
            }

            var natural = (Vector2)sprite.bounds.size;
            if (natural.x <= 0f || natural.y <= 0f)
            {
                return;
            }

            var viewHeight = targetCamera.orthographicSize * 2f * Mathf.Max(1f, overscan);
            var viewWidth = viewHeight * Mathf.Max(0.1f, targetCamera.aspect);
            var scale = viewHeight / natural.y;
            var tile = natural * scale;

            transform.localScale = new Vector3(scale, scale, 1f);
            spriteRenderer.drawMode = SpriteDrawMode.Tiled;
            spriteRenderer.tileMode = SpriteTileMode.Continuous;
            var height = tileVertically ? viewHeight + tile.y * 2f : tile.y;
            spriteRenderer.size = new Vector2((viewWidth + tile.x * 2f) / scale, height / scale);

            // Shifting by whole tiles is invisible, so the image only appears to move by
            // the parallax fraction of the camera movement.
            var cameraPosition = targetCamera.transform.position;
            var x = cameraPosition.x - Mathf.Repeat(cameraPosition.x * parallax, tile.x);
            var y = tileVertically
                ? cameraPosition.y - Mathf.Repeat(cameraPosition.y * parallax, tile.y)
                : cameraPosition.y;
            transform.position = new Vector3(x, y, transform.position.z);
        }
    }
}
