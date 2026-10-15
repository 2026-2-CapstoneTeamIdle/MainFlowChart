using System;
using System.Collections.Generic;
using UnityEngine;

namespace TeamIdle.GameTemplate.Core
{
    public sealed class ValidationProbe : MonoBehaviour
    {
        [Serializable]
        public sealed class Record
        {
            public string eventId = string.Empty;
            public string message = string.Empty;
            public bool passed;
            public float realtimeSeconds;
        }

        [Serializable]
        private sealed class RecordCollection
        {
            public List<Record> records = new();
        }

        private readonly List<Record> records = new();

        public IReadOnlyList<Record> Records => records;

        public bool HasFailure { get; private set; }

        public void Pass(string eventId, string message)
        {
            AddRecord(eventId, message, true);
        }

        public void Fail(string eventId, string message)
        {
            HasFailure = true;
            AddRecord(eventId, message, false);
        }

        public string ExportJson(bool prettyPrint = true)
        {
            return JsonUtility.ToJson(
                new RecordCollection { records = new List<Record>(records) },
                prettyPrint
            );
        }

        private void AddRecord(string eventId, string message, bool passed)
        {
            records.Add(
                new Record
                {
                    eventId = eventId,
                    message = message,
                    passed = passed,
                    realtimeSeconds = Time.realtimeSinceStartup,
                }
            );

            var prefix = passed ? "VALIDATION_PASS" : "VALIDATION_FAIL";
            Debug.Log($"{prefix}:{eventId}:{message}", this);
        }
    }
}
