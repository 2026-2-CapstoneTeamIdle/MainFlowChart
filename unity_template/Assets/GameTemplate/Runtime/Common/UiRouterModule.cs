using System;
using System.Collections.Generic;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.Common
{
    public sealed class UiRouterModule : GameModuleBehaviour
    {
        [Serializable]
        private sealed class Route
        {
            public string routeId = string.Empty;
            public GameObject panel;
        }

        [SerializeField]
        private List<Route> routes = new();
        public override string ModuleId => "ui_router";
        public string CurrentRoute { get; private set; } = string.Empty;

        public bool Show(string routeId)
        {
            var found = false;
            foreach (var route in routes)
            {
                var active = route.routeId == routeId;
                if (route.panel != null)
                    route.panel.SetActive(active);
                found |= active;
            }
            if (found)
                CurrentRoute = routeId;
            return found;
        }

        protected override void OnInitialize(GameContext context) => context.Register(this);
    }
}
