using System;

namespace TeamIdle.GameTemplate.Core
{
    [AttributeUsage(AttributeTargets.Class, AllowMultiple = false, Inherited = false)]
    public sealed class GeneratedGameModuleAttribute : Attribute
    {
        public GeneratedGameModuleAttribute(string moduleId)
        {
            ModuleId = moduleId;
        }

        public string ModuleId { get; }
    }
}
