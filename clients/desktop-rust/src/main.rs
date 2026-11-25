#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::env;
use std::path::PathBuf;
use tao::{
    event::{Event, KeyEvent, WindowEvent},
    event_loop::{ControlFlow, EventLoop},
    keyboard::KeyCode,
    window::{Fullscreen, WindowBuilder},
};
use wry::{WebContext, WebViewBuilder};

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

    let event_loop = EventLoop::new();
    let window = WindowBuilder::new()
        .with_title(&title)
        .with_maximized(true)
        .build(&event_loop)
        .expect("Failed to create CapsStream window");

    let mut web_context = WebContext::new(Some(data_dir()));
    let _webview = WebViewBuilder::with_web_context(&mut web_context)
        .with_url(&url)
        .with_background_color((5, 5, 8, 255))
        .with_autoplay(true)
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
        })
        .build(&window)?;

    event_loop.run(move |event, _, control_flow| {
        *control_flow = ControlFlow::Wait;
        if let Event::WindowEvent { event, .. } = event {
            match event {
                WindowEvent::CloseRequested => *control_flow = ControlFlow::Exit,
                WindowEvent::KeyboardInput {
                    event: KeyEvent { physical_key: KeyCode::F11, state: tao::event::ElementState::Pressed, repeat: false, .. },
                    ..
                } => {
                    let is_fs = window.fullscreen().is_some();
                    window.set_fullscreen(if is_fs { None } else { Some(Fullscreen::Borderless(None)) });
                }
                _ => {}
            }
        }
    });
}
