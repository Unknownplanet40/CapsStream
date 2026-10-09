using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;
using CapsStream_WinUI.ViewModels;
using CapsStream.Core.Models;

namespace CapsStream_WinUI.Pages;

public sealed partial class HomePage : Page
{
    public HomeViewModel ViewModel { get; } = new();

    public HomePage()
    {
        InitializeComponent();
    }

    protected override async void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        await ViewModel.LoadDataAsync();
    }

    private void HeroPlay_Click(object sender, RoutedEventArgs e)
    {
        if (ViewModel.HeroItem != null)
        {
            Frame.Navigate(typeof(PlayerPage), ViewModel.HeroItem);
        }
    }

    private void HeroDetails_Click(object sender, RoutedEventArgs e)
    {
        if (ViewModel.HeroItem != null)
        {
            Frame.Navigate(typeof(PlayerPage), ViewModel.HeroItem);
        }
    }

    private void Card_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button { Tag: MediaItem item })
        {
            Frame.Navigate(typeof(PlayerPage), item);
        }
    }
}
