using System;
using System.Collections.ObjectModel;
using System.Threading.Tasks;
using CapsStream.Core.Models;
using CapsStream.Data;
using CapsStream.Data.Repositories;
using CommunityToolkit.Mvvm.ComponentModel;

namespace CapsStream_WinUI.ViewModels;

public class HomeViewModel : ObservableObject
{
    private readonly MediaRepository _mediaRepo;

    private bool _isLoading;
    public bool IsLoading
    {
        get => _isLoading;
        set => SetProperty(ref _isLoading, value);
    }

    private MediaItem? _heroItem;
    public MediaItem? HeroItem
    {
        get => _heroItem;
        set => SetProperty(ref _heroItem, value);
    }

    private bool _hasHero;
    public bool HasHero
    {
        get => _hasHero;
        set => SetProperty(ref _hasHero, value);
    }

    private bool _hasContinueWatching;
    public bool HasContinueWatching
    {
        get => _hasContinueWatching;
        set => SetProperty(ref _hasContinueWatching, value);
    }

    private bool _hasRecentlyAdded;
    public bool HasRecentlyAdded
    {
        get => _hasRecentlyAdded;
        set => SetProperty(ref _hasRecentlyAdded, value);
    }

    private bool _hasTrendingMovies;
    public bool HasTrendingMovies
    {
        get => _hasTrendingMovies;
        set => SetProperty(ref _hasTrendingMovies, value);
    }

    private bool _hasPopularSeries;
    public bool HasPopularSeries
    {
        get => _hasPopularSeries;
        set => SetProperty(ref _hasPopularSeries, value);
    }

    private bool _hasAnime;
    public bool HasAnime
    {
        get => _hasAnime;
        set => SetProperty(ref _hasAnime, value);
    }

    private string _statusMessage = string.Empty;
    public string StatusMessage
    {
        get => _statusMessage;
        set => SetProperty(ref _statusMessage, value);
    }

    public ObservableCollection<MediaItem> ContinueWatching { get; } = new();
    public ObservableCollection<MediaItem> RecentlyAdded { get; } = new();
    public ObservableCollection<MediaItem> TrendingMovies { get; } = new();
    public ObservableCollection<MediaItem> PopularSeries { get; } = new();
    public ObservableCollection<MediaItem> AnimeList { get; } = new();

    public HomeViewModel()
    {
        _mediaRepo = new MediaRepository(CapsDb.Default);
    }

    public async Task LoadDataAsync()
    {
        IsLoading = true;
        try
        {
            // 1. Featured Hero Billboard
            var hero = await _mediaRepo.GetFeaturedHeroAsync();
            HeroItem = hero;
            HasHero = hero != null;

            // 2. Continue Watching
            ContinueWatching.Clear();
            var continueItems = await _mediaRepo.GetContinueWatchingAsync(1, 15);
            foreach (var item in continueItems) ContinueWatching.Add(item);
            HasContinueWatching = ContinueWatching.Count > 0;

            // 3. Recently Added
            RecentlyAdded.Clear();
            var recentItems = await _mediaRepo.GetRecentlyAddedAsync(20);
            foreach (var item in recentItems) RecentlyAdded.Add(item);
            HasRecentlyAdded = RecentlyAdded.Count > 0;

            // 4. Trending / Top Rated Movies
            TrendingMovies.Clear();
            var movies = await _mediaRepo.GetTopRatedAsync(MediaType.Movie, 20);
            foreach (var item in movies) TrendingMovies.Add(item);
            HasTrendingMovies = TrendingMovies.Count > 0;

            // 5. Popular TV Series
            PopularSeries.Clear();
            var series = await _mediaRepo.GetTopRatedAsync(MediaType.Series, 20);
            foreach (var item in series) PopularSeries.Add(item);
            HasPopularSeries = PopularSeries.Count > 0;

            // 6. Anime
            AnimeList.Clear();
            var anime = await _mediaRepo.GetAllAsync(MediaType.Anime);
            foreach (var item in anime) AnimeList.Add(item);
            HasAnime = AnimeList.Count > 0;

            StatusMessage = $"CapsStream library connected ({RecentlyAdded.Count} recent titles)";
        }
        catch (Exception ex)
        {
            StatusMessage = $"Error: {ex.Message}";
            System.Diagnostics.Debug.WriteLine($"[HomeViewModel] Error: {ex}");
        }
        finally
        {
            IsLoading = false;
        }
    }
}
