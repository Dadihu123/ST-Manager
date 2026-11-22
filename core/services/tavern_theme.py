"""Theme fields recognized by the targets' native theme importers."""

THEME_FIELDS = (
    'blur_strength', 'main_text_color', 'italics_text_color', 'underline_text_color',
    'quote_text_color', 'blur_tint_color', 'chat_tint_color', 'user_mes_blur_tint_color',
    'bot_mes_blur_tint_color', 'shadow_color', 'shadow_width', 'border_color',
    'font_scale', 'fast_ui_mode', 'waifuMode', 'avatar_style', 'chat_display',
    'toastr_position', 'noShadows', 'chat_width', 'timer_enabled', 'timestamps_enabled',
    'timestamp_model_icon', 'mesIDDisplay_enabled', 'hideChatAvatars_enabled',
    'message_token_count_enabled', 'expand_message_actions', 'enableZenSliders',
    'enableLabMode', 'hotswap_enabled', 'custom_css', 'bogus_folders',
    'zoomed_avatar_magnification', 'reduced_motion', 'compact_input_area',
    'show_swipe_num_all_messages', 'click_to_edit', 'media_display',
)


def get_theme_settings(theme):
    return {key: theme[key] for key in THEME_FIELDS if key in theme}


def activate_sent_theme(power_user, theme, *, tauri=False):
    """Persist the selected theme and its appearance for the target's next startup."""
    name = theme['name']
    if tauri:
        current = power_user.get('theme')
        fallback = power_user.get('theme_fallback') or current
        power_user['theme_fallback'] = name
        if current and current not in (name, fallback):
            # A character or chat theme is active. The new fallback applies once it is left.
            return
    power_user.update(get_theme_settings(theme))
    power_user['theme'] = name
