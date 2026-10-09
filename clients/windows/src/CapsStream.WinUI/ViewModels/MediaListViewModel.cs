using System;
using System.Collections.ObjectModel;
using System.Threading.Tasks;
using CapsStream.Core.Models;
using CapsStream.Data;
using CapsStream.Data.Repositories;
using CommunityToolkit.Mvvm.ComponentModel;

namespace CapsStream_WinUI.ViewModels;

public class MediaListViewModel : ObservableObject
{
    private readonly MediaRepository _mediaRepo;
    private readonly string? _mediaType;

    private bool _isLoading;
    public bool IsLoading
    {
        get => _isLoading;
        set => SetProperty(ref _isLoading, value);
    }

    private string _searchQuery = string.Empty;
    public string SearchQuery
    {
        get => _searchQuery;
        set => SetProperty(ref _searchQuery, value);
    }

    public ObservableCollection<MediaItem> Items { get; } = new();

    public MediaListViewModel(string? mediaType)
    {
        _mediaType = mediaType;
        _mediaRepo = new MediaRepository(CapsDb.Default);
    }

    public async Task LoadItemsAsync()
    {
        IsLoading = true;
        try
        {
            Items.Clear();
            var results = string.IsNullOrWhiteSpace(SearchQuery)
                ? await _mediaRepo.GetAllAsync(_mediaType)
                : await _mediaRepo.SearchAsync(SearchQuery, _mediaType);

            foreach (var item in results)
            {
                Items.Add(item);
            }
        }
        catch (Exception ex)
        {
            System.Diagnostics.Debug.WriteLine($"[MediaListViewModel] Error loading items: {ex.Message}");
        }
        finally
        {
            IsLoading = false;
        }
    }
}
