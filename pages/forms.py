from django import forms
from .models import BookCategory

class BookCategoryForm(forms.ModelForm):
    class Meta:
        model = BookCategory
        fields = ['book', 'category', 'award_level', 'year']
        widgets = {
            'book': forms.HiddenInput(),  # Book will be selected via search
            'category': forms.Select(attrs={'class': 'form-control'}),
            'award_level': forms.Select(attrs={'class': 'form-control'}),
            'year': forms.NumberInput(attrs={'class': 'form-control'}),
        }
