using System;
using System.Collections.Generic;
using UnityEngine;

namespace TeamIdle.GameTemplate.TowerDefense
{
    public sealed class PathFollower2D : MonoBehaviour
    {
        [SerializeField]
        private float speed = 2f;
        private IReadOnlyList<Transform> waypoints;
        private int waypointIndex;
        public event Action ReachedEnd;

        public void SetPath(IReadOnlyList<Transform> nextWaypoints)
        {
            waypoints = nextWaypoints;
            waypointIndex = 0;
        }

        private void Update()
        {
            if (waypoints == null || waypointIndex >= waypoints.Count)
                return;
            var destination = waypoints[waypointIndex];
            if (destination == null)
            {
                waypointIndex++;
                return;
            }
            transform.position = Vector3.MoveTowards(
                transform.position,
                destination.position,
                speed * Time.deltaTime
            );
            if ((transform.position - destination.position).sqrMagnitude > 0.001f)
                return;
            waypointIndex++;
            if (waypointIndex >= waypoints.Count)
                ReachedEnd?.Invoke();
        }
    }
}
