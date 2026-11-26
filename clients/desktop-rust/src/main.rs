#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::env;
use std::path::PathBuf;
use tao::{
    event::{Event, KeyEvent, WindowEvent},
    event_loop::{ControlFlow, EventLoopBuilder},
    keyboard::KeyCode,
    window::{Fullscreen, Icon, Window, WindowBuilder},
};
use wry::{WebContext, WebViewBuilder};
#[cfg(target_os = "windows")]
use wry::WebViewBuilderExtWindows;

#[derive(Debug, Clone, Copy)]
enum UserEvent {
    SetFullscreen(bool),
}

fn apply_fullscreen(window: &Window, enter: bool, was_maximized: &mut bool) {
    let currently_fs = window.fullscreen().is_some();
    if enter == currently_fs {
        return;
    }
    if enter {
        *was_maximized = window.is_maximized();
        window.set_decorations(false);
        window.set_fullscreen(Some(Fullscreen::Borderless(None)));
    } else {
        window.set_fullscreen(None);
        window.set_decorations(true);
        if *was_maximized {
            window.set_maximized(true);
        }
    }
}

fn parse_arg(args: &[String], flag: &str, default: &str) -> String {
    args.windows(2)
        .find(|w| w[0] == flag)
        .map(|w| w[1].clone())
        .unwrap_or_else(|| default.to_string())
}

fn data_dir() -> PathBuf {
    if let Ok(exe) = env::current_exe() {
        if let Some(dir) = exe.parent() {
            let candidate = dir.join("webview2_profile");
            if std::fs::create_dir_all(&candidate).is_ok() {
                return candidate;
            }
        }
    }
    env::temp_dir().join("capsstream_webview2")
}

fn is_local_url(url: &str) -> bool {
    url.starts_with("http://127.0.0.1")
        || url.starts_with("http://localhost")
        || url.starts_with("https://127.0.0.1")
        || url.starts_with("https://localhost")
}

fn main() -> wry::Result<()> {
    let args: Vec<String> = env::args().collect();
    let url = parse_arg(&args, "--url", "http://127.0.0.1:8000");
    let title = parse_arg(&args, "--title", "CapsStream");

    let event_loop = EventLoopBuilder::<UserEvent>::with_user_event().build();
    let proxy = event_loop.create_proxy();
    let window_icon = Icon::from_rgba(include_bytes!("icon_32.rgba").to_vec(), 32, 32).ok();
    let window = WindowBuilder::new()
        .with_title(&title)
        .with_window_icon(window_icon)
        .with_maximized(true)
        .build(&event_loop)
        .expect("Failed to create CapsStream window");

    let mut web_context = WebContext::new(Some(data_dir()));
    let builder = WebViewBuilder::with_web_context(&mut web_context)
        .with_url(&url)
        .with_background_color((5, 5, 8, 255))
        .with_autoplay(true)
        .with_initialization_script(
            "document.addEventListener('fullscreenchange', function () {\
                if (window.ipc && window.ipc.postMessage) {\
                    window.ipc.postMessage(document.fullscreenElement ? 'fs:1' : 'fs:0');\
                }\
            });",
        )
        .with_ipc_handler(move |req| {
            let body = req.body().as_str();
            if body == "fs:1" {
                let _ = proxy.send_event(UserEvent::SetFullscreen(true));
            } else if body == "fs:0" {
                let _ = proxy.send_event(UserEvent::SetFullscreen(false));
            }
        })
        .with_navigation_handler(|nav_url| {
            if is_local_url(&nav_url) || nav_url.starts_with("blob:") || nav_url.starts_with("data:") {
                true
            } else {
                #[cfg(target_os = "windows")]
                let _ = std::process::Command::new("cmd")
                    .args(["/C", "start", "", &nav_url])
                    .spawn();
                false
            }
        });
    #[cfg(target_os = "windows")]
    let builder = builder.with_additional_browser_args(
        "--enable-features=PlatformHEVCDecoderSupport --autoplay-policy=no-user-gesture-required",
    );
    let _webview = builder.build(&window)?;

    let mut was_maximized = true;
    event_loop.run(move |event, _, control_flow| {
        *control_flow = ControlFlow::Wait;
        match event {
            Event::UserEvent(UserEvent::SetFullscreen(enter)) => {
                apply_fullscreen(&window, enter, &mut was_maximized);
            }
            Event::WindowEvent { event, .. } => match event {
                WindowEvent::CloseRequested => *control_flow = ControlFlow::Exit,
                WindowEvent::KeyboardInput {
                    event: KeyEvent { physical_key: KeyCode::F11, state: tao::event::ElementState::Pressed, repeat: false, .. },
                    ..
                } => {
                    let enter = window.fullscreen().is_none();
                    apply_fullscreen(&window, enter, &mut was_maximized);
                }
                _ => {}
            },
            _ => {}
        }
    });
}
