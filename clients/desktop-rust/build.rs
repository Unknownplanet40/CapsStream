fn main() {
    if std::env::var_os("CARGO_CFG_WINDOWS").is_some() {
        let mut res = winresource::WindowsResource::new();
        res.set_icon("../../static/img/favicon.ico");
        res.compile().expect("Failed to embed CapsStream Windows icon");
    }
}
