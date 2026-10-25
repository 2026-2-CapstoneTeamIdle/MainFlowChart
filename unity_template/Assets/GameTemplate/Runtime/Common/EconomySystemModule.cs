using System;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.Common
{
    public sealed class EconomySystemModule : GameModuleBehaviour
    {
        [SerializeField]
        private int startingCurrency;
        public override string ModuleId => "economy_system";
        public int Currency { get; private set; }
        public event Action<int> Changed;

        public void Add(int amount)
        {
            Currency = Mathf.Max(0, Currency + amount);
            Changed?.Invoke(Currency);
        }

        public bool Spend(int amount)
        {
            if (amount < 0 || Currency < amount)
                return false;
            Currency -= amount;
            Changed?.Invoke(Currency);
            return true;
        }

        protected override void OnInitialize(GameContext context)
        {
            Currency = Mathf.Max(0, startingCurrency);
            context.Register(this);
        }
    }
}
