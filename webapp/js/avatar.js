/* Authenticated image requests work in Telegram and the Android WebView. */
(function (root) {
    root.AvatarMedia = {
        async load(token, signal) {
            const response = await fetch('/app/api/profile/avatar', {
                headers: { Authorization: `Bearer ${token}` },
                cache: 'no-store',
                signal,
            });
            if (response.status === 204) return null;
            if (!response.ok) {
                const error = new Error('Avatar unavailable');
                error.status = response.status;
                throw error;
            }
            const blob = await response.blob();
            if (!['image/jpeg', 'image/png', 'image/gif', 'image/webp'].includes(blob.type)) {
                throw new Error('Invalid avatar image');
            }
            return blob;
        },
    };
})(globalThis);
