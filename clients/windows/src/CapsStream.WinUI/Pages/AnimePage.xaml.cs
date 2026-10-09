using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;
using CapsStream_WinUI.ViewModels;
using CapsStream.Core.Models;

namespace CapsStream_WinUI.Pages;

public sealed partial class AnimePage : Page
{
    public MediaListViewModel ViewModel { get; } = new(MediaType.Anime);

    public AnimePage()
    {
        InitializeComponent();
    }

    protected override async void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        await ViewModel.LoadItemsAsync();
    }

    private async void Search_TextChanged(AutoSuggestBox sender, AutoSuggestBoxTextChangedEventArgs args)
    {
        if (args.Reason == AutoSuggestionBoxTextChangeReason.UserInput)
        {
            ViewModel.SearchQuery = sender.Text;
            if (string.IsNullOrWhiteSpace(sender.Text))
            {
                await ViewModel.LoadItemsAsync();
            }
        }
    }

    private async void Search_QuerySubmitted(AutoSuggestBox sender, AutoSuggestBoxQuerySubmittedEventArgs args)
    {
        ViewModel.SearchQuery = sender.Text;
        await ViewModel.LoadItemsAsync();
    }

    private void MediaItem_Click(object sender, ItemClickEventArgs e)
    {
        if (e.ClickedItem is MediaItem item)
        {
            Frame.Navigate(typeof(PlayerPage), item);
        }
    }
}
