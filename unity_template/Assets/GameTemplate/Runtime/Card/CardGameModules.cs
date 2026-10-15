using System;
using System.Collections.Generic;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.Card
{
    [Serializable]
    public sealed class CardData
    {
        public string cardId = string.Empty;
        public string displayName = string.Empty;
        public int cost;
        public int power;

        [TextArea]
        public string description = string.Empty;
    }

    public sealed class DeckSystemModule : GameModuleBehaviour
    {
        [SerializeField]
        private List<CardData> startingDeck = new();

        [SerializeField]
        private int startingHandSize = 5;

        private readonly List<CardData> drawPile = new();
        private readonly List<CardData> hand = new();
        private readonly List<CardData> discardPile = new();

        public override string ModuleId => "deck_system";

        public IReadOnlyList<CardData> Hand => hand;

        public event Action HandChanged;

        public CardData Draw()
        {
            if (drawPile.Count == 0)
            {
                ReshuffleDiscard();
            }

            if (drawPile.Count == 0)
            {
                return null;
            }

            var lastIndex = drawPile.Count - 1;
            var card = drawPile[lastIndex];
            drawPile.RemoveAt(lastIndex);
            hand.Add(card);
            HandChanged?.Invoke();
            return card;
        }

        public bool Discard(CardData card)
        {
            if (card == null || !hand.Remove(card))
            {
                return false;
            }

            discardPile.Add(card);
            HandChanged?.Invoke();
            return true;
        }

        protected override void OnInitialize(GameContext context)
        {
            drawPile.AddRange(startingDeck);
            Shuffle(drawPile);
            for (var index = 0; index < startingHandSize; index++)
            {
                Draw();
            }

            context.Register(this);
        }

        private void ReshuffleDiscard()
        {
            drawPile.AddRange(discardPile);
            discardPile.Clear();
            Shuffle(drawPile);
        }

        private static void Shuffle(List<CardData> cards)
        {
            for (var index = cards.Count - 1; index > 0; index--)
            {
                var swapIndex = UnityEngine.Random.Range(0, index + 1);
                (cards[index], cards[swapIndex]) = (cards[swapIndex], cards[index]);
            }
        }
    }

    public sealed class CardResourceSystemModule : GameModuleBehaviour
    {
        [SerializeField]
        private int maximum = 3;

        public override string ModuleId => "card_resource_system";

        public int Current { get; private set; }

        public event Action<int, int> Changed;

        public void Refill()
        {
            Current = Mathf.Max(0, maximum);
            Changed?.Invoke(Current, maximum);
        }

        public bool Spend(int amount)
        {
            if (amount < 0 || Current < amount)
            {
                return false;
            }

            Current -= amount;
            Changed?.Invoke(Current, maximum);
            return true;
        }

        public void IncreaseMaximum(int amount = 1)
        {
            maximum = Mathf.Max(0, maximum + amount);
            Refill();
        }

        protected override void OnInitialize(GameContext context)
        {
            Refill();
            context.Register(this);
        }
    }

    public sealed class TurnSystemModule : GameModuleBehaviour
    {
        public enum TurnOwner
        {
            Player,
            Opponent,
        }

        public override string ModuleId => "turn_system";

        public int TurnNumber { get; private set; }

        public TurnOwner CurrentOwner { get; private set; }

        public event Action<int, TurnOwner> TurnStarted;

        public void EndTurn()
        {
            CurrentOwner = CurrentOwner == TurnOwner.Player ? TurnOwner.Opponent : TurnOwner.Player;
            if (CurrentOwner == TurnOwner.Player)
            {
                TurnNumber++;
            }

            TurnStarted?.Invoke(TurnNumber, CurrentOwner);
        }

        protected override void OnInitialize(GameContext context)
        {
            TurnNumber = 1;
            CurrentOwner = TurnOwner.Player;
            context.Register(this);
            TurnStarted?.Invoke(TurnNumber, CurrentOwner);
        }
    }

    public sealed class CardEffectSystemModule : GameModuleBehaviour
    {
        private CardResourceSystemModule resources;
        private DeckSystemModule deck;

        public override string ModuleId => "card_effect_system";

        public event Action<CardData> CardPlayed;

        public bool Play(CardData card, Action<CardData> applyEffect)
        {
            if (card == null || !resources.Spend(card.cost))
            {
                return false;
            }

            applyEffect?.Invoke(card);
            deck.Discard(card);
            CardPlayed?.Invoke(card);
            return true;
        }

        protected override void OnInitialize(GameContext context)
        {
            resources = context.GetRequired<CardResourceSystemModule>();
            deck = context.GetRequired<DeckSystemModule>();
            context.Register(this);
        }
    }
}
