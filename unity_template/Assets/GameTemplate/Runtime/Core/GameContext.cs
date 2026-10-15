using System;
using System.Collections.Generic;

namespace TeamIdle.GameTemplate.Core
{
    public sealed class GameContext
    {
        private readonly Dictionary<Type, object> services = new();

        public GameContext(GameTemplateConfig config, ValidationProbe validation)
        {
            Config = config;
            Validation = validation;
        }

        public GameTemplateConfig Config { get; }

        public ValidationProbe Validation { get; }

        public void Register<T>(T service)
            where T : class
        {
            if (service == null)
            {
                throw new ArgumentNullException(nameof(service));
            }

            services[typeof(T)] = service;
        }

        public bool TryGet<T>(out T service)
            where T : class
        {
            if (services.TryGetValue(typeof(T), out var value) && value is T typedValue)
            {
                service = typedValue;
                return true;
            }

            service = null;
            return false;
        }

        public T GetRequired<T>()
            where T : class
        {
            if (TryGet<T>(out var service))
            {
                return service;
            }

            throw new InvalidOperationException(
                $"Required game service is missing: {typeof(T).Name}"
            );
        }
    }
}
