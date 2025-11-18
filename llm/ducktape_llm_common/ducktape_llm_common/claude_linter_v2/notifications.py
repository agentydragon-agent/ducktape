"""Desktop notification functions for Claude Linter v2."""

import logging

logger = logging.getLogger(__name__)


def send_desktop_notification(
    title: str, message: str, urgency: str = "critical", replaces_id: int = 0
) -> int:
    """Send desktop notification via D-Bus.

    Args:
        title: Notification title
        message: Notification body (will be truncated to 200 chars)
        urgency: Urgency level (low, normal, critical)
        replaces_id: ID of notification to replace (0 = new notification)

    Returns:
        ID of the notification

    Raises:
        ImportError: If dbus module is not available
        OSError: If D-Bus session bus is not available
    """
    import dbus

    # Map urgency strings to D-Bus urgency levels
    urgency_map = {
        "low": 0,
        "normal": 1,
        "critical": 2,
    }

    # Get session bus
    bus = dbus.SessionBus()

    # Get notification interface
    notify_obj = bus.get_object(
        "org.freedesktop.Notifications", "/org/freedesktop/Notifications"
    )
    notify_iface = dbus.Interface(notify_obj, "org.freedesktop.Notifications")

    # Send notification
    notification_id = notify_iface.Notify(
        "Claude Linter",  # app_name
        replaces_id,  # replaces_id (0 = new notification)
        "",  # app_icon (empty = default)
        title,
        message[:200],  # body (truncated)
        [],  # actions
        {
            "urgency": dbus.Byte(urgency_map.get(urgency, 2)),
        },  # hints
        -1,  # expire_timeout (-1 = default)
    )

    return notification_id


def close_desktop_notification(notification_id: int) -> None:
    """Close a desktop notification via D-Bus.

    Args:
        notification_id: ID of the notification to close

    Raises:
        ImportError: If dbus module is not available
        OSError: If D-Bus session bus is not available
    """
    import dbus

    try:
        # Get session bus
        bus = dbus.SessionBus()

        # Get notification interface
        notify_obj = bus.get_object(
            "org.freedesktop.Notifications", "/org/freedesktop/Notifications"
        )
        notify_iface = dbus.Interface(notify_obj, "org.freedesktop.Notifications")

        # Close notification
        notify_iface.CloseNotification(notification_id)
    except (dbus.exceptions.DBusException, AttributeError) as e:
        logger.debug(f"Failed to close notification {notification_id}: {e}")
