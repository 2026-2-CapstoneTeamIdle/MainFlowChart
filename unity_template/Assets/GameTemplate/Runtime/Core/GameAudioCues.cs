using System;

namespace TeamIdle.GameTemplate.Core
{
    // Gameplay code raises cue IDs here; generated sounds subscribe without a hard reference.
    // Keep the IDs in sync with SOUND_CUE_KEYWORDS in game_pipeline/asset_specs.py.
    public static class GameAudioCues
    {
        public const string SceneStart = "scene_start";
        public const string GameClear = "game_clear";
        public const string GameOver = "game_over";
        public const string LevelUp = "level_up";
        public const string Checkpoint = "checkpoint";
        public const string Jump = "jump";
        public const string CardPlay = "card_play";
        public const string Pickup = "pickup";
        public const string PlayerHit = "player_hit";
        public const string EnemyHit = "enemy_hit";
        public const string Attack = "attack";
        public const string Activity = "activity";
        public const string Ui = "ui";
        public const string TowerBuilt = "tower_built";
        public const string TowerUpgraded = "tower_upgraded";
        public const string EnemyDefeated = "enemy_defeated";
        public const string BaseDamaged = "base_damaged";
        public const string WaveStarted = "wave_started";
        public const string BossArrived = "boss_arrived";
        public const string BossSpawn = "boss_spawn";

        public static event Action<string> Raised;

        public static void Raise(string cueId) => Raised?.Invoke(cueId);
    }
}
