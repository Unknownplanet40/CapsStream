using System;
using System.IO;
using System.Threading.Tasks;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;
using Windows.Media.Core;
using Windows.Media.Playback;
using Windows.Storage;
using CapsStream.Core.Models;

namespace CapsStream_WinUI.Pages;

public sealed partial class PlayerPage : Page
{
    private MediaItem? _currentItem;

    public PlayerPage()
    {
        InitializeComponent();
        Loaded += PlayerPage_Loaded;
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);

        if (e.Parameter is MediaItem item)
        {
            _currentItem = item;
            TitleText.Text = item.DisplayTitle;
            SubtitleText.Text = $"{item.DisplayYear} • {item.QualityBadge} • {item.FilePath}";
        }
    }

    private async void PlayerPage_Loaded(object sender, RoutedEventArgs e)
    {
        if (_currentItem != null)
        {
            await StartPlaybackAsync(_currentItem);
        }
    }

    private async Task StartPlaybackAsync(MediaItem item)
    {
        try
        {
            var rawPath = item.FilePath;
            if (string.IsNullOrWhiteSpace(rawPath))
            {
                ShowError("Media item does not have a valid file path in the database.");
                return;
            }

            var normalizedPath = Path.GetFullPath(rawPath.Replace('/', Path.DirectorySeparatorChar));
            if (!File.Exists(normalizedPath))
            {
                ShowError($"File was not found on disk at: {normalizedPath}");
                return;
            }

            var mediaPlayer = new MediaPlayer
            {
                AutoPlay = true
            };

            mediaPlayer.MediaOpened += (s, args) =>
            {
                DispatcherQueue.TryEnqueue(() =>
                {
                    PlayerErrorBar.IsOpen = false;
                    mediaPlayer.Play();
                });
            };

            mediaPlayer.MediaFailed += (s, args) =>
            {
                DispatcherQueue.TryEnqueue(() =>
                {
                    var ext = Path.GetExtension(normalizedPath).ToUpperInvariant();
                    ShowError(
                        $"Windows Media Player failed to decode this file ({args.Error}). " +
                        $"Format: {ext}. If this is an MKV or HEVC video, Windows Media Foundation may require the Microsoft Store HEVC/MKV extension."
                    );
                });
            };

            MediaSource? source = null;
            try
            {
                var storageFile = await StorageFile.GetFileFromPathAsync(normalizedPath);
                source = MediaSource.CreateFromStorageFile(storageFile);
            }
            catch
            {
                var uri = new Uri(normalizedPath);
                source = MediaSource.CreateFromUri(uri);
            }

            mediaPlayer.Source = source;
            Player.SetMediaPlayer(mediaPlayer);
            mediaPlayer.Play();
        }
        catch (Exception ex)
        {
            ShowError($"Failed to initialize playback: {ex.Message}");
        }
    }

    private void ShowError(string message)
    {
        PlayerErrorBar.IsOpen = true;
        PlayerErrorBar.Message = message;
    }

    protected override void OnNavigatingFrom(NavigatingCancelEventArgs e)
    {
        base.OnNavigatingFrom(e);
        try
        {
            Player.MediaPlayer?.Pause();
            Player.SetMediaPlayer(null);
        }
        catch { }
    }

    private void BackButton_Click(object sender, RoutedEventArgs e)
    {
        if (Frame.CanGoBack)
        {
            Frame.GoBack();
        }
    }
}
